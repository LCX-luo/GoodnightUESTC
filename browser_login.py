"""Visible, isolated Edge login with a disposable profile in private local storage."""
import re
import os
import threading
import time
import tempfile
import logging
from pathlib import Path
from core import ORIGIN, CAS, browser_allowed, verify_session
from urllib.parse import urlsplit
from network import NETWORK

LOGIN_URL = CAS + '/login?service=https%3A%2F%2Fjzsz.uestc.edu.cn%2F'
ENTRY_URL = ORIGIN + '/daily-checkin/checkLogin?appId=294'


class BrowserLogin:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.state = {'state': 'idle', 'message': '尚未开始登录'}
        self.thread = None
        self.started_at = None

    def status(self):
        with self.lock:
            result = dict(self.state)
            if self.started_at is not None:
                result['elapsed'] = round(time.monotonic()-self.started_at, 1)
            return result

    def update(self, state, message, reason=None):
        with self.lock:
            self.state = {'state': state, 'message': message}
            if reason:
                self.state['reason'] = reason

    def start(self, student, password):
        if not re.fullmatch(r'\d{8,20}', student) or not 1 <= len(password) <= 256:
            raise ValueError('请输入有效学号和密码。')
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('登录窗口已打开，请先完成或取消当前登录。')
            self.cancelled.clear()
            self.started_at = time.monotonic()
            self.state = {'state': 'opening', 'message': '正在打开独立 Edge 登录窗口…'}
            self.thread = threading.Thread(target=self.run, args=(student, password), daemon=True)
            self.thread.start()

    def cancel(self):
        self.cancelled.set()

    def run(self, student, password):
        stage = 'prepare_browser_temp'
        try:
            from playwright.sync_api import sync_playwright
            # Node's os.tmpdir() may resolve to an unwritable inherited Windows TEMP.
            # Explicitly place BOTH its artifacts and Edge profile in our private store.
            base = self.store.directory / 'browser-temp'
            base.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='edge-', dir=base, ignore_cleanup_errors=True) as work, sync_playwright() as p:
                stage = 'start_edge'
                context = p.chromium.launch_persistent_context(
                    str(Path(work) / 'profile'), channel='msedge', headless=False, timeout=15000,
                    artifacts_dir=str(Path(work) / 'artifacts'), service_workers='block',
                    env={**os.environ, 'TEMP': work, 'TMP': work},
                    **NETWORK.browser_options('idas.uestc.edu.cn'))
                try:
                    previous = self.store.session()
                    if previous and previous['student_id'] == student:
                        context.add_cookies(previous['cookies'])
                    # Protect even a manually navigated business page from attendance writes.
                    context.route('**/*', lambda route: route.continue_() if browser_allowed(
                        route.request.method, route.request.url) else route.abort('blockedbyclient'))
                    context.route_web_socket('**/*', lambda socket: socket.close())
                    page = context.new_page()
                    user_agent = page.evaluate('navigator.userAgent')
                    stage = 'open_school'
                    page.goto(LOGIN_URL, wait_until='commit', timeout=20000)
                    try:
                        if urlsplit(page.url).hostname == 'jzsz.uestc.edu.cn':
                            raise ValueError('Existing session already redirected to portal')
                        account_input = page.locator('input#username:visible').first
                        password_input = page.locator('input#password:visible').first
                        account_input.fill(student, timeout=10000)
                        password_input.click(timeout=5000)
                        # School marks this field readonly to suppress browser autofill.
                        # Removing the presentation attribute does not skip authentication.
                        password_input.evaluate("element => element.removeAttribute('readonly')")
                        password_input.fill(password, timeout=5000)
                        password = ''
                        login = page.locator('#login_submit:visible').first
                        if login.count() and login.is_visible():
                            login.click(timeout=5000, no_wait_after=True)
                    except Exception:
                        # Changed selectors or manual authentication: leave the visible UI available.
                        password = ''
                    stage = 'wait_school_authorization'
                    self.update('waiting', '请在 Edge 中完成登录、验证码或二次验证；完成后会自动获取会话。')
                    deadline = time.monotonic() + 600
                    entered = False
                    last_probe = 0
                    while time.monotonic() < deadline and not self.cancelled.is_set():
                        if page.is_closed():
                            self.update('cancelled', '登录窗口已关闭，可重新开始。')
                            return
                        cookies = context.cookies([ORIGIN, CAS])
                        if (urlsplit(page.url).hostname == 'jzsz.uestc.edu.cn'
                                and any(c['name'] == 'SESSION' and c['domain'].lstrip('.') == 'jzsz.uestc.edu.cn' for c in cookies)):
                            if not entered:
                                entered = True
                                try:
                                    self.update('verifying', '正在打开智慧学工签到应用…')
                                    page.goto(ENTRY_URL, wait_until='commit', timeout=10000)
                                except Exception:
                                    pass
                            if time.monotonic() - last_probe >= 2:
                                last_probe = time.monotonic()
                                snapshot = {'student_id': student, 'cookies': context.cookies([ORIGIN, CAS]),
                                            'user_agent': user_agent, 'saved_at': time.time()}
                                # Read only the official H5 origin; keep authorization encrypted
                                # with its session, never in status responses or console output.
                                current = urlsplit(page.url)
                                if current.hostname == 'jzsz.uestc.edu.cn' and current.path.startswith('/daily-checkin-h5/'):
                                    try:
                                        ticket = page.evaluate("() => sessionStorage.getItem('daily-checkin-operation-ticket') || ''")
                                        if isinstance(ticket, str) and re.fullmatch(r'[!-~]{1,8192}', ticket):
                                            snapshot['operation_ticket'] = ticket
                                    except Exception:
                                        pass
                                try:
                                    self.update('verifying', '正在验证学校会话并保存 Cookie…')
                                    verify_session(snapshot)
                                except Exception:
                                    self.update('waiting', '已获取登录 Cookie，等待智慧学工授权完成；请按 Edge 页面提示操作。')
                                else:
                                    if self.cancelled.is_set():
                                        self.update('cancelled', '已取消登录，会话未保存。')
                                        return
                                    self.store.save_session(snapshot)
                                    self.update('success', '登录成功，Cookie 已自动加密保存；未提交打卡记录。')
                                    return
                        page.wait_for_timeout(1000)
                    self.update('cancelled', '已取消登录。' if self.cancelled.is_set() else '登录已超时，请重试。')
                finally:
                    try:
                        context.close()
                    except Exception:
                        logging.getLogger(__name__).warning('Edge close failed; reason=browser_close_failed')
        except Exception as error:
            # Never log the traceback or exception text: it can include URLs or cookies.
            detail = str(error).lower()
            if isinstance(error, PermissionError) or 'eperm' in detail or 'access is denied' in detail:
                reason, message = 'browser_temp_permission', 'Edge 临时目录无法写入，请检查本机应用目录权限后重试。'
            elif 'executable' in detail and ('exist' in detail or 'not found' in detail):
                reason, message = 'edge_not_installed', '未找到 Edge 浏览器，请安装后重新打开登录窗口。'
            elif stage == 'open_school':
                reason, message = 'school_page_unavailable', 'Edge 已打开，但学校登录页暂时无法访问，请检查网络后重试。'
            else:
                reason, message = 'browser_start_failed', '登录窗口未能完成，请重新打开 Edge 登录；可查看本机诊断原因。'
            logging.getLogger(__name__).warning('Browser login failed stage=%s reason=%s', stage, reason)
            self.update('error', message, reason=reason)
