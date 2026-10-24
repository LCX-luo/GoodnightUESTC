"""Python 3.13 companion. JSON pipes only; never submits attendance.

Uses a separately installed, pinned MioYiSama/moon-uestc checkout. No upstream
main.py import: that entry point performs a real check-in with fixed coordinates.
"""
import base64
import json
import sys
import time
from pathlib import Path


def emit(event, **values):
    print(json.dumps({'event': event, **values}, ensure_ascii=True), flush=True)


def run(config):
    import httpx2
    from moon_uestc import MoonClient, WeChatClient
    from moon_uestc.wechat_models import WeChatCredentials

    class AuthOnlyTransport(httpx2.BaseTransport):
        def __init__(self):
            self.inner = httpx2.HTTPTransport(retries=0, trust_env=False)

        def handle_request(self, request):
            allowed = {
                ('GET', '/daily-checkin/api/auth/user-info'),
                ('GET', '/platform-app/api/auth/user-info'),
                ('POST', '/platform-app/api/auth/check-bind'),
                ('POST', '/platform-app/api/auth/checkin-ticket'),
            }
            if (request.url.scheme != 'https' or request.url.host != 'jzsz.uestc.edu.cn'
                    or request.url.port not in (None, 443)
                    or (request.method, request.url.path) not in allowed):
                raise RuntimeError('school_request_blocked')
            return self.inner.handle_request(request)

        def close(self):
            self.inner.close()

    def school(session=None):
        return MoonClient(session=session, timeout=15, transport=AuthOnlyTransport())

    # The browser identity is checked before QR authorization or code consumption.
    emit('step', message='正在验证浏览器学校身份…')
    with school(config['session']) as h5:
        expected = h5.auth.user_info().data.user_data
    if expected.username != config['student_id']:
        raise RuntimeError('school_identity_mismatch')
    with WeChatClient(timeout=45, transport=httpx2.HTTPTransport(retries=0, trust_env=False)) as wechat:
        cached = config.get('credentials')
        if cached:
            credentials = WeChatCredentials.model_validate(cached)
            if credentials.expires_at <= time.time() + 60:
                emit('step', message='正在刷新微信授权凭据…')
                credentials = wechat.refresh(credentials)
        else:
            if not config.get('allow_qr'):
                raise RuntimeError('wechat_authorization_required')
            qr = wechat.create_qr()
            emit('qr', image=base64.b64encode(qr.image).decode('ascii'))
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                polled = wechat.poll_qr(qr.uuid)
                if polled.status == 'authorized' and polled.code:
                    credentials = wechat.exchange_code(polled.code)
                    break
                if polled.status in ('cancelled', 'expired'):
                    raise RuntimeError('wechat_qr_expired')
                if polled.status == 'scanned':
                    emit('step', message='已扫码，请在微信确认授权。')
                time.sleep(1)
            else:
                raise RuntimeError('wechat_qr_expired')
        # Persist rotated tokens before subsequent protocol operations can fail.
        emit('credentials', credentials={
            'openid': credentials.openid.get_secret_value(),
            'access_token': credentials.access_token.get_secret_value(),
            'refresh_token': credentials.refresh_token.get_secret_value(),
            'expires_at': credentials.expires_at,
        })
        emit('step', message='正在获取微信 code 并建立小程序会话…')
        code = wechat.get_code(app_id='wxaa78bf2905f01cee', credentials=credentials)
        with school() as bootstrap:
            binding = bootstrap.auth.check_wechat_bind(code=code).data
        if not binding.bind or binding.session_id is None:
            raise RuntimeError('wechat_school_not_bound')
        with school(binding.session_id) as mini:
            emit('step', message='正在核对微信绑定的学校账号…')
            actual = mini.auth.mini_program_user_info().data.user_data
            if actual.id != expected.id or actual.username != expected.username:
                raise RuntimeError('wechat_identity_mismatch')
            emit('step', message='身份一致，正在用第二个新 code 换取操作票据…')
            fresh = wechat.get_code(app_id='wxaa78bf2905f01cee', credentials=credentials)
            ticket = mini.auth.request_checkin_ticket(code=fresh).data.ticket
        emit('complete', ticket=ticket.get_secret_value(), student_id=expected.username,
             submitted=False, code_lengths=[len(code.get_secret_value()), len(fresh.get_secret_value())])


if __name__ == '__main__':
    # Arguments contain paths only. All authentication material arrives over stdin.
    sys.path.insert(0, str(Path(sys.argv[1]).resolve() / 'src'))
    try:
        run(json.loads(sys.stdin.readline()))
    except Exception as error:
        safe = {'school_identity_mismatch', 'school_request_blocked', 'wechat_identity_mismatch',
                'wechat_authorization_required', 'wechat_qr_expired', 'wechat_school_not_bound'}
        reason = str(error) if type(error) is RuntimeError and str(error) in safe else type(error).__name__
        code = getattr(error, 'code', None)
        emit('error', reason=reason, apiCode=code if type(code) is int else None)
        sys.exit(1)
