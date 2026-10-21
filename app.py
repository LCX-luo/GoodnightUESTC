import os
import hashlib
import json
from pathlib import Path
import secrets
import threading
import time
from flask import Flask, jsonify, request, session, send_from_directory
from werkzeug.exceptions import HTTPException
from core import ROOT, DATA_ROOT, LocalStore, ToolError, offline_test, online_test, now
from browser_login import BrowserLogin
from checkin import Attempts, prepare_checkin, submit_checkin
from progress import Progress

MESSAGES = {
    'write_blocked': '测试模式已拦截学校写入请求。',
    'invalid_location': '请输入有效的经纬度。',
    'invalid_configured_coordinates': '经纬度超出有效范围或不是有限数字。',
    'coordinate_system_mismatch': '请选择 WGS-84 或 GCJ-02。',
    'session_rejected': '学校会话已失效，请重新登录。',
    'portal_session_rejected': '学校会话已失效，请重新登录。',
    'micro_app_unauthorized': '智慧学工打卡应用未授权，请重新登录并完成页面提示。',
    'network_error': '无法连接学校网络，请检查连接后重试。',
    'timeout': '学校请求超时，请稍后重试。',
    'business_date_mismatch': '学校返回的记录日期不是今天。',
    'invalid_schedule': '学校未返回当前有效打卡时段。',
    'location_required': '请先选择并保存实际位置。',
    'outside_allowed_location': '所选位置不在学校允许范围内，无法提交。',
    'outside_checkin_window': '当前不在学校允许的签到时段内。',
    'already_recorded': '学校当天已有签到、报告或豁免记录，无需重复提交。',
    'business_date_changed': '日期已变化，请重新检查学校记录。',
}


def create_app(data_dir=None):
    app = Flask(__name__, static_folder=str(ROOT / 'static'))
    app.secret_key = secrets.token_bytes(32)
    app.config.update(MAX_CONTENT_LENGTH=16384, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict')
    store = LocalStore(data_dir or DATA_ROOT / 'private-data')
    login = BrowserLogin(store)
    attempts = Attempts(store.directory)
    test_lock = threading.Lock()
    operation = Progress()
    pending = {}
    pending_lock = threading.Lock()
    app.extensions.update(local_store=store, browser_login=login)

    @app.before_request
    def protect():
        if request.host not in ('127.0.0.1:8090', 'localhost:8090'):
            return jsonify(error='仅允许本机访问。'), 403
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            expected = 'http://' + request.host
            if request.headers.get('Origin') != expected:
                return jsonify(error='请求来源不匹配，请从本机页面操作。'), 403
            token = session.get('csrf', '')
            if not token or not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), token):
                return jsonify(error='页面会话已更新，请刷新页面。'), 403

    @app.after_request
    def headers(response):
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://tile.openstreetmap.org; connect-src 'self'; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'self'; object-src 'none'")
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(ToolError)
    def school_error(error):
        return jsonify(error=MESSAGES.get(error.reason, '检查未通过：' + error.reason),
                       reason=error.reason, stage=error.stage, submitted=False), 400

    @app.errorhandler(Exception)
    def unexpected(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        return jsonify(error='操作未完成，请重试或查看使用说明。', submitted=False), 500

    @app.get('/')
    def index():
        return send_from_directory(ROOT / 'static', 'index.html')

    @app.get('/api/status')
    def status():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(24)
        saved = store.session()
        return jsonify(product='GoodNightUESTC', csrf=session['csrf'], mode='manual', schoolWritesEnabled=True,
                       account=({'student_id': saved['student_id'],
                                 'saved_at': saved['saved_at'], 'cookie_count': len(saved['cookies'])} if saved else None),
                       location=store.location(), login=login.status(), operation=operation.snapshot())

    @app.post('/api/login')
    def start_login():
        data = request.get_json()
        if not isinstance(data, dict) or not all(isinstance(data.get(k), str) for k in ('student_id', 'password')):
            return jsonify(error='请输入学号和密码。'), 400
        if test_lock.locked():
            return jsonify(error='正在执行检查，请稍后再登录。'), 409
        try:
            login.start(data['student_id'].strip(), data['password'])
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(ok=True, login=login.status()), 202

    @app.post('/api/login/cancel')
    def cancel_login():
        login.cancel()
        return jsonify(ok=True)

    @app.post('/api/session/forget')
    def forget():
        if login.thread and login.thread.is_alive():
            return jsonify(error='请先取消登录，等待登录窗口关闭后再清除。'), 409
        store.forget()
        return jsonify(ok=True)

    @app.post('/api/location')
    def location():
        return jsonify(ok=True, location=store.save_location(request.get_json()))

    def binding(snapshot, location):
        return hashlib.sha256(json.dumps({'account': snapshot['student_id'], 'location': location},
                                         sort_keys=True).encode()).hexdigest()

    @app.post('/api/checkin/prepare')
    def prepare():
        if login.thread and login.thread.is_alive():
            return jsonify(error='请先完成或取消登录。'), 409
        if not test_lock.acquire(blocking=False):
            return jsonify(error='另一项检查正在进行，请稍后重试。'), 409
        try:
            snapshot, point = store.session(), store.location()
            if not snapshot:
                return jsonify(error='请先登录本人学校账号。'), 400
            with operation.operation('prepare'):
                preview = prepare_checkin(snapshot, point, progress=operation.step)
            token = secrets.token_urlsafe(32)
            with pending_lock:
                for key in list(pending):
                    if pending[key]['expires'] < time.monotonic():
                        pending.pop(key)
                if len(pending) >= 32:
                    return jsonify(error='待确认操作过多，请稍后重试。'), 429
                pending[token] = {'owner': session['csrf'], 'binding': binding(snapshot, point),
                                  'day': preview['businessDate'],
                                  'address': preview.get('address'),
                                  'expires': time.monotonic()+120}
            return jsonify(ok=True, confirmation=token, preview=preview, expires_in=120)
        finally:
            test_lock.release()

    @app.post('/api/checkin')
    def checkin():
        data = request.get_json()
        if (not isinstance(data, dict) or data.get('confirm') is not True
                or data.get('actual_location_confirmed') is not True
                or not isinstance(data.get('confirmation'), str)):
            return jsonify(error='请先预检查，并明确确认实际位置和本次提交。', submitted=False), 400
        if login.thread and login.thread.is_alive():
            return jsonify(error='请先完成或取消登录。', submitted=False), 409
        if not test_lock.acquire(blocking=False):
            return jsonify(error='有任务正在执行，请勿重复点击。', submitted=False), 409
        try:
            snapshot, point = store.session(), store.location()
            with pending_lock:
                ticket = pending.pop(data['confirmation'], None)
            if (not ticket or ticket['expires'] < time.monotonic()
                    or ticket['day'] != now().date().isoformat()
                    or ticket['owner'] != session.get('csrf') or not snapshot or not point
                    or ticket['binding'] != binding(snapshot, point)):
                return jsonify(error='确认已过期或账号、位置已变化，请重新预检查。', submitted=False), 400
            with operation.operation('checkin'):
                result = submit_checkin(snapshot, point, attempts, address=ticket.get('address'), progress=operation.step)
            return jsonify(ok=True, result=result)
        finally:
            test_lock.release()

    @app.post('/api/test/offline')
    def offline():
        return jsonify(ok=True, result=offline_test(store.location()))

    @app.post('/api/test/online')
    def online():
        if login.thread and login.thread.is_alive():
            return jsonify(error='请先完成或取消登录。'), 409
        if not test_lock.acquire(blocking=False):
            return jsonify(error='检查正在进行中。'), 409
        try:
            snapshot = store.session()
            if not snapshot:
                return jsonify(error='请先通过 Edge 登录并自动导入 Cookie。'), 400
            with operation.operation('online'):
                result = online_test(snapshot, store.location(), progress=operation.step)
            return jsonify(ok=True, result=result)
        finally:
            test_lock.release()

    return app


if __name__ == '__main__':
    import sys
    if '--self-test' in sys.argv:
        from selftest import run
        run()
        raise SystemExit(0)
    from waitress import create_server
    import webbrowser
    server = create_server(create_app(), host='127.0.0.1', port=8090, threads=4)
    print('晚安成电 · 本机签到 http://127.0.0.1:8090', flush=True)
    if os.environ.get('UESTC_NO_OPEN') != '1':
        webbrowser.open('http://127.0.0.1:8090/')
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
