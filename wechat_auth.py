"""Encrypted, account-bound controller for the isolated authorization worker."""
import base64
import hashlib
import json
import subprocess
import threading
import time
from pathlib import Path
from core import ROOT, DATA_ROOT, ToolError

PINNED_COMMIT = 'f8a93c3bc4d62cea879b76560c49c9646387b386'
ERRORS = {
    'school_identity_mismatch': '浏览器中的学校账号与保存的学号不一致，请重新登录。',
    'wechat_identity_mismatch': '微信绑定账号与学校登录账号不一致，未取票、未提交。',
    'wechat_school_not_bound': '请先在官方智慧学工小程序完成本人账号绑定。',
    'wechat_authorization_required': '请先点击微信授权并扫码。',
    'wechat_qr_expired': '二维码已取消或过期，可重新发起授权。',
    'WeChatAuthorizationError': '微信拒绝授权或凭据已失效，请清除微信授权后重新扫码。',
    'WeChatProtocolError': '微信协议连接未完成；请检查网络，当前没有提交签到。',
    'AuthenticationError': '学校会话失效，请重新登录学校账号。',
    'CheckinTicketError': '学校未签发操作票据，请核对授权与账号。',
}


def session_binding(snapshot):
    return hashlib.sha256(json.dumps({k: snapshot.get(k) for k in
                          ('student_id', 'cookies', 'saved_at')}, sort_keys=True).encode()).hexdigest()


def school_session(snapshot):
    values = {c['value'] for c in snapshot['cookies'] if c['name'] == 'SESSION'
              and c['domain'].lstrip('.') == 'jzsz.uestc.edu.cn'
              and (c.get('expires', -1) <= 0 or c['expires'] > time.time())
              and '/daily-checkin/api/auth/user-info'.startswith(c.get('path', '/'))}
    if len(values) != 1:
        raise ToolError('wechat_school_session_required', 'wechat_authorization')
    return values.pop()


class WeChatAuthorization:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.thread = None
        self.process = None
        self.cancelled = False
        self.state = {'state': 'idle', 'message': '可先验证微信授权和取票，测试不会提交签到。'}
        self.runtime = DATA_ROOT / 'private-data' / 'wechat-runtime' / 'Scripts' / 'python.exe'
        self.source = DATA_ROOT / 'private-data' / 'moon-uestc-reference'

    def ready(self):
        return self.runtime.exists() and (self.source / 'src/moon_uestc/wechat.py').exists()

    def cached(self, snapshot):
        with self.store.lock:
            path = self.store.directory / 'wechat.enc'
            saved = self.store.vault.open(path.read_bytes(), 'wechat-authorization') if path.exists() else None
            return saved.get('credentials') if saved and saved.get('student_id') == snapshot['student_id'] else None

    def status(self):
        with self.lock:
            result = dict(self.state)
            result.update(runtimeReady=self.ready(), active=bool(self.thread and self.thread.is_alive()))
        saved = self.store.session()
        result['hasCredentials'] = bool(saved and self.cached(saved))
        result['ticketReady'] = bool(saved and saved.get('operation_ticket') and
                                     saved.get('operation_ticket_expires_at', 0) > time.time() + 15)
        return result

    def start(self, snapshot):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ToolError('wechat_busy')
            if not self.ready():
                raise ToolError('wechat_runtime_required')
            school_session(snapshot)
            self.cancelled = False
            self.state = {'state': 'working', 'message': '正在验证学校身份并准备微信授权…'}
            self.thread = threading.Thread(target=self._background, args=(snapshot,), daemon=True)
            self.thread.start()

    def cancel(self):
        with self.lock:
            self.cancelled = True
            if self.process and self.process.poll() is None:
                self.process.terminate()
            self.state = {'state': 'cancelled', 'message': '已取消微信授权，没有提交签到。'}

    def forget(self):
        self.cancel()
        with self.store.lock:
            (self.store.directory / 'wechat.enc').unlink(missing_ok=True)
            saved = self.store.session()
            if saved:
                for key in list(saved):
                    if key.startswith('operation_ticket'):
                        saved.pop(key)
                self.store.save_session(saved)

    def _background(self, snapshot):
        try:
            self.execute(snapshot, allow_qr=True)
        except Exception as error:
            with self.lock:
                if not self.cancelled:
                    reason = error.reason if isinstance(error, ToolError) else 'worker_failed'
                    previous = self.state
                    self.state = {'state': 'error', 'reason': reason,
                                  'message': ERRORS.get(reason, '授权测试未完成，没有提交签到。')}
                    if previous.get('apiCode') is not None:
                        self.state['apiCode'] = previous['apiCode']

    def execute(self, snapshot, allow_qr=False):
        config = {'student_id': snapshot['student_id'], 'session': school_session(snapshot),
                  'credentials': self.cached(snapshot), 'allow_qr': allow_qr}
        if not allow_qr and not config['credentials']:
            raise ToolError('wechat_authorization_required')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, 'CREATE_NO_WINDOW') else {}
        proc = subprocess.Popen([str(self.runtime), '-u', str(ROOT / 'wechat_worker.py'), str(self.source)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, encoding='utf-8', **options)
        with self.lock:
            self.process = proc
            if self.cancelled:
                proc.terminate()
        # A hard deadline also covers upstream QR polling or HTTP calls hanging.
        timer = threading.Timer(330 if allow_qr else 150, lambda: proc.terminate() if proc.poll() is None else None)
        timer.daemon = True
        timer.start()
        complete = False
        try:
            proc.stdin.write(json.dumps(config, ensure_ascii=True) + '\n')
            proc.stdin.close()
            for line in proc.stdout:
                if len(line) > 2000000:
                    raise ToolError('wechat_worker_protocol')
                event = json.loads(line)
                with self.lock, self.store.lock:
                    if self.cancelled:
                        raise ToolError('wechat_cancelled')
                    current = self.store.session()
                    if not current or session_binding(current) != session_binding(snapshot):
                        raise ToolError('wechat_account_changed')
                    kind = event['event']
                    if kind == 'credentials':
                        self.state.pop('qr', None)
                        self.state['state'] = 'working'
                        value = {'student_id': snapshot['student_id'], 'credentials': event['credentials']}
                        temp = self.store.directory / 'wechat.new'
                        temp.write_bytes(self.store.vault.seal(value, 'wechat-authorization'))
                        temp.replace(self.store.directory / 'wechat.enc')
                    elif kind == 'qr':
                        base64.b64decode(event['image'], validate=True)
                        self.state.update(state='qr', message='请用本人微信扫码，在手机确认授权。',
                                          qr='data:image/png;base64,' + event['image'])
                    elif kind == 'step':
                        self.state.update(message=event['message'])
                    elif kind == 'error':
                        self.state['apiCode'] = event.get('apiCode')
                        raise ToolError(event['reason'], 'wechat_authorization', event.get('apiCode'))
                    elif kind == 'complete':
                        import re
                        if (event.get('submitted') is not False or event.get('student_id') != snapshot['student_id']
                                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', event['ticket'])):
                            raise ToolError('wechat_worker_protocol')
                        current.update(operation_ticket=event['ticket'], operation_ticket_source='wechat-companion',
                                       operation_ticket_expires_at=time.time() + 300)
                        self.store.save_session(current)
                        credential_file = self.store.directory / 'wechat.enc'
                        if credential_file.exists():
                            authorization = self.store.vault.open(credential_file.read_bytes(), 'wechat-authorization')
                            authorization['last_verified_at'] = time.time()
                            temp = self.store.directory / 'wechat.new'
                            temp.write_bytes(self.store.vault.seal(authorization, 'wechat-authorization'))
                            temp.replace(credential_file)
                        self.state = {'state': 'success', 'message': '身份核对与取票成功。未提交签到；本地最多暂存 5 分钟。',
                                      'submitted': False, 'ticketLength': len(event['ticket']),
                                      'codeLengths': event['code_lengths']}
                        complete = True
            if proc.wait(timeout=5) != 0 or not complete:
                raise ToolError('wechat_worker_incomplete')
            return self.store.session()
        finally:
            timer.cancel()
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=10)
            proc.stdout.close()
            with self.lock:
                if self.process is proc:
                    self.process = None

    def for_submission(self, snapshot):
        # Legacy imported tickets remain compatible; native credentials get a new
        # one-use ticket for each explicit final confirmation.
        if self.cached(snapshot):
            with self.lock:
                self.cancelled = False
                self.state = {'state': 'working', 'message': '正在获取本次签到授权…'}
            return self.execute(snapshot, allow_qr=False)
        return snapshot

    def consume_local_ticket(self):
        with self.store.lock:
            saved = self.store.session()
            if saved:
                for key in list(saved):
                    if key.startswith('operation_ticket'):
                        saved.pop(key)
                self.store.save_session(saved)
