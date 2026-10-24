"""Phone-local OAuth and school authorization; no attendance write capability."""
import base64
import hashlib
import http.client
import http.cookiejar
import json
import re
import secrets
import ssl
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
import certifi
from wechat_protocol._wechat_mmtls import get_code

OAUTH = 'https://open.weixin.qq.com/connect/qrconnect'
CALLBACK = 'https://yybadaccess.3g.qq.com/pc_yyb/pcyyb_oauth'
AUTH = 'https://yybadaccess.3g.qq.com/pc_yyb_auth/'
SCHOOL = 'https://jzsz.uestc.edu.cn'
ALLOWED_SCHOOL = {
    ('GET', '/daily-checkin/api/auth/user-info'),
    ('GET', '/platform-app/api/auth/user-info'),
    ('POST', '/platform-app/api/auth/check-bind'),
    ('POST', '/platform-app/api/auth/checkin-ticket'),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))

    def request(self, method, url, body=None, headers=None, timeout=20):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or parsed.port not in (None, 443) or parsed.username
                or parsed.hostname not in {'open.weixin.qq.com', 'long.open.weixin.qq.com',
                                           'yybadaccess.3g.qq.com', 'jzsz.uestc.edu.cn'}):
            raise RuntimeError('request_blocked')
        if parsed.hostname == 'jzsz.uestc.edu.cn' and (method, parsed.path) not in ALLOWED_SCHOOL:
            raise RuntimeError('request_blocked')
        request = urllib.request.Request(url, data=body, method=method,
                                        headers={'User-Agent': 'Mozilla/5.0', **(headers or {})})
        try:
            response = self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            content = response.read(2_000_001)
            if len(content) > 2_000_000:
                raise RuntimeError('response_too_large')
            return response.code, response.headers, content

    def school(self, method, path, session=None, body=None):
        headers = {'platform': 'mp-weixin' if path.startswith('/platform-app/') else 'h5'}
        if session:
            if re.search(r'[\s";,\\]', session):
                raise RuntimeError('school_session_invalid')
            headers['Cookie'] = 'SESSION=' + session
        if body is not None:
            headers['Content-Type'] = 'application/json'
        status, _, raw = self.request(method, SCHOOL + path,
                                      json.dumps(body).encode() if body is not None else None, headers)
        if status != 200:
            raise RuntimeError('school_http_' + str(status))
        envelope = json.loads(raw)
        valid = envelope.get('ok') is True if path.startswith('/platform-app/') else (
            envelope.get('ok') is not False and envelope.get('code') == 0)
        if not valid:
            raise RuntimeError('school_code_' + str(envelope.get('code', 'unknown')))
        return envelope['data']


def signed(client, operation, body, credentials=None):
    data = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
    timestamp, nonce = str(int(time.time() * 1000)), str(secrets.randbelow(10000))
    # Byte layout follows the reviewed application's application-bao protocol.
    signature = hashlib.md5((data.decode() + timestamp + 'wgrdg373hy26ww2' + nonce).encode()).hexdigest()
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json',
               'Ual-Access-Businessid': 'pc_yyb_auth', 'Ual-Access-Timestamp': timestamp,
               'Ual-Access-Nonce': nonce, 'Ual-Access-Signature': signature}
    if credentials:
        values = [credentials[k] for k in ('openid', 'access_token', 'refresh_token')]
        if any(re.search(r'[\r\n;"\\]', value) for value in values):
            raise RuntimeError('credential_invalid')
        headers['Cookie'] = 'openid={}; accesstoken={}; refreshtoken={}'.format(*values)
    status, _, content = client.request('POST', AUTH + operation, data, headers, 40)
    if status != 200:
        raise RuntimeError('wechat_http_' + str(status))
    result = json.loads(content)
    if type(result.get('code')) is not int or result['code'] != 0:
        raise RuntimeError('wechat_credential_rejected')
    return result


def login_buffer(client, credentials):
    result = signed(client, 'pcyyb_get_wx_login_buffer_auth', {'extInfo': {
        'listS': {'unionid': {'value': [credentials['openid']]}, 'user_id': {'value': [credentials['openid']]},
                  'access_token': {'value': [credentials['access_token']]}},
        'listI': {'user_type': {'value': [0]}}}}, credentials)
    return result['ext_info']['list_s']['login_buffer']['value'][0]


def cancelled(callback):
    if callback.cancelled():
        raise RuntimeError('cancelled')


def poll_result(body):
    """Parse the protocol status; never expose OAuth code in diagnostics."""
    text = body.decode()
    result = re.search(r'wx_errcode\s*=\s*(\d+)', text)
    if not result:
        raise RuntimeError('qr_unavailable')
    status = int(result[1])
    if status == 405:
        match = re.search(r"wx_code\s*=\s*'([^']+)'", text)
        if not match:
            raise RuntimeError('qr_unavailable')
        return status, match[1]
    if status == 403:
        raise RuntimeError('cancelled')
    if status == 402:
        raise RuntimeError('qr_expired')
    if status not in (404, 408):
        raise RuntimeError('qr_status_unrecognized')
    return status, None


def poll_failure(error):
    """Classify by exception type only: messages can contain credential URLs."""
    if isinstance(error, urllib.error.URLError):
        error = error.reason
    if isinstance(error, ssl.SSLCertVerificationError):
        return 'qr_tls_certificate', False
    if isinstance(error, ssl.SSLError):
        return 'qr_tls_failed', False
    if isinstance(error, (TimeoutError, socket.timeout)):
        return 'qr_network_timeout', True
    if isinstance(error, http.client.RemoteDisconnected):
        return 'qr_remote_disconnected', True
    if isinstance(error, http.client.IncompleteRead):
        return 'qr_incomplete_read', True
    if isinstance(error, http.client.BadStatusLine):
        return 'qr_bad_status_line', True
    if isinstance(error, ConnectionError):
        return 'qr_connection_failed', True
    if isinstance(error, socket.gaierror):
        return 'qr_dns_failed', True
    if isinstance(error, UnicodeDecodeError):
        return 'qr_response_encoding', False
    return 'qr_network_failed', False


def wait_for_qr(client, uuid, callback):
    # Only these read-only status GETs can retry. OAuth code exchange and all
    # school writes remain single attempts. Keep exactly the original QR uuid.
    deadline, retries, last_status = time.monotonic() + 210, 0, None
    while time.monotonic() < deadline:
        cancelled(callback)
        failure, retryable = None, False
        try:
            http_status, _, body = client.request(
                'GET', 'https://long.open.weixin.qq.com/connect/l/qrconnect?' +
                urllib.parse.urlencode({'uuid': uuid, '_': str(int(time.time()*1000))}),
                timeout=min(45, max(0.1, deadline-time.monotonic())))
            if http_status != 200:
                failure = 'qr_http_' + str(http_status)
                retryable = 500 <= http_status <= 599
            else:
                status, oauth_code = poll_result(body)
        except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError,
                http.client.HTTPException, UnicodeDecodeError, socket.gaierror) as error:
            failure, retryable = poll_failure(error)
        if failure:
            if not retryable or retries >= 3 or time.monotonic() + 1 >= deadline:
                raise RuntimeError(failure) from None
            retries += 1
            callback.diagnostic(failure)
            callback.progress('二维码状态连接中断，正在重连；请保留原二维码，不要重复授权。')
            time.sleep(1)
            continue
        if status != last_status:
            callback.diagnostic({408: 'qr_poll_pending', 404: 'qr_poll_scanned',
                                 405: 'qr_poll_authorized'}[status])
            last_status = status
        if status == 405:
            return oauth_code
        if status == 404:
            callback.progress('已识别二维码，请在微信确认授权，然后返回本应用。')
        time.sleep(1)
    raise RuntimeError('qr_expired')


def acquire(session, cache_json, callback, allow_qr):
    try:
        return _acquire(session, cache_json, callback, allow_qr)
    except Exception as error:
        # No Python exception message/traceback may cross the bridge as a
        # diagnostic: urllib and TLS messages can embed URLs or headers.
        fixed = str(error) if isinstance(error, RuntimeError) else ''
        if re.fullmatch(r'(?:cancelled|authorization_required|identity_mismatch|school_not_bound|'
                        r'request_blocked|response_too_large|school_session_invalid|credential_invalid|'
                        r'wechat_credential_rejected|oauth_credentials_missing|ticket_invalid|'
                        r'qr_[a-z_]+|(?:qr|school|wechat)_http_[1-5]\d{2}|school_code_\d{1,9})', fixed):
            raise RuntimeError(fixed) from None
        kind = type(error).__name__.lower()
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', kind):
            kind = 'unknown'
        errno = getattr(error, 'errno', None)
        suffix = '_errno_' + str(errno) if type(errno) is int and 0 <= errno <= 9999 else ''
        raise RuntimeError('python_failure_' + kind + suffix) from None


def _acquire(session, cache_json, callback, allow_qr):
    client = Client()
    callback.progress('正在核对学校登录身份…')
    user = client.school('GET', '/daily-checkin/api/auth/user-info', session)['userData']
    credentials = json.loads(cache_json) if cache_json else None
    if credentials and credentials.get('school_user_id') != user['id']:
        credentials = None
    if credentials is None:
        if not allow_qr:
            raise RuntimeError('authorization_required')
        params = {'appid': 'wxd44977328b36e647', 'redirect_uri': CALLBACK + '?login_type=WX',
                  'response_type': 'code', 'scope': 'snsapi_login,snsapi_runtime_pcsdk',
                  'state': 'web', 'fast_login': '1', 'self_redirect': 'true'}
        status, _, body = client.request('GET', OAUTH + '?' + urllib.parse.urlencode(params))
        match = re.search(r'/connect/qrcode/([^"\x27>\s]+)', body.decode())
        if status != 200 or not match or not re.fullmatch(r'[A-Za-z0-9._~-]{1,256}', match[1]):
            raise RuntimeError('qr_unavailable')
        uuid = match[1]
        status, _, image = client.request('GET', 'https://open.weixin.qq.com/connect/qrcode/' + uuid)
        if status != 200 or not image:
            raise RuntimeError('qr_unavailable')
        callback.qr(base64.b64encode(image).decode())
        oauth_code = wait_for_qr(client, uuid, callback)
        cancelled(callback)
        callback.progress('微信已确认，正在接收授权凭据…')
        callback_client = Client()
        url = CALLBACK + '?' + urllib.parse.urlencode({'login_type': 'WX', 'code': oauth_code, 'state': 'web'})
        for _ in range(6):
            status, headers, _ = callback_client.request('GET', url)
            values = {c.name: c.value for c in callback_client.cookies if
                      ('yybadaccess.3g.qq.com' == c.domain.lstrip('.') or
                       'yybadaccess.3g.qq.com'.endswith('.' + c.domain.lstrip('.'))) and
                      '/pc_yyb/pcyyb_oauth'.startswith(c.path)}
            if values.get('openid') and values.get('accesstoken'):
                credentials = {'openid': values['openid'], 'access_token': values['accesstoken'],
                               'refresh_token': values.get('refreshtoken', ''),
                               'expires_at': int(time.time()) + int(values.get('expires_in', '7200')),
                               'school_user_id': user['id']}
                break
            if status not in (301, 302, 303, 307, 308):
                raise RuntimeError('oauth_credentials_missing')
            url = urllib.parse.urljoin(url, headers.get('Location', ''))
            if urllib.parse.urlsplit(url).hostname != 'yybadaccess.3g.qq.com':
                raise RuntimeError('request_blocked')
        else:
            raise RuntimeError('oauth_credentials_missing')
    elif credentials['expires_at'] <= time.time() + 60:
        callback.progress('正在刷新微信授权…')
        result = signed(client, 'pcyyb_refresh_token_auth', {'userInfo': {
            'openId': credentials['openid'], 'refreshToken': credentials['refresh_token'],
            'accessToken': credentials['access_token'], 'loginType': 'WX'}})['user_info']
        credentials.update(access_token=result['access_token'], refresh_token=result.get('refresh_token') or credentials['refresh_token'],
                           expires_at=int(time.time()) + int(result['expires_in']))
    callback.credentials(json.dumps(credentials))
    cancelled(callback)
    callback.progress('正在申请微信 code 并建立小程序会话…')
    first = get_code(login_buffer(client, credentials), 'wxaa78bf2905f01cee', timeout=45)
    binding = client.school('POST', '/platform-app/api/auth/check-bind', body={'code': first, 'sn': ''})
    if binding.get('bind') is not True or not binding.get('sessionId'):
        raise RuntimeError('school_not_bound')
    mini_session = binding['sessionId']
    mini = client.school('GET', '/platform-app/api/auth/user-info', mini_session)['userData']
    if mini['id'] != user['id'] or mini['username'] != user['username']:
        raise RuntimeError('identity_mismatch')
    cancelled(callback)
    callback.progress('账号一致，正在申请本次操作票据…')
    second = get_code(login_buffer(client, credentials), 'wxaa78bf2905f01cee', timeout=45)
    ticket = client.school('POST', '/platform-app/api/auth/checkin-ticket', mini_session, {'code': second})['ticket']
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', ticket):
        raise RuntimeError('ticket_invalid')
    cancelled(callback)
    return json.dumps({'ticket': ticket, 'username': user['username'], 'school_user_id': user['id']})


def self_test():
    """No networking: Android ABI, OpenSSL, protocol import and cipher round trip."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from wechat_protocol._wechat_wire import pb_len, pb_parse
    cipher = AESGCM(bytes(16))
    assert cipher.decrypt(bytes(12), cipher.encrypt(bytes(12), b'android', None), None) == b'android'
    assert pb_parse(pb_len(1, b'android'))
    return True
