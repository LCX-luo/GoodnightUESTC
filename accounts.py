"""Local authorization profiles; no attendance endpoint is exposed here."""
import json
import re
import threading
import uuid
import time
from pathlib import Path
from flask import jsonify, request, send_from_directory
from werkzeug.wrappers import Response
from core import LocalStore

ALLOWED = frozenset({'status', 'login', 'login/cancel', 'session/forget', 'location',
                     'wechat/start', 'wechat/cancel', 'wechat/forget', 'test/online', 'test/offline'})


def install_accounts(app, store, root, factory):
    directory = store.directory / 'profiles'
    directory.mkdir(exist_ok=True)
    index = directory / 'index.json'
    lock = threading.RLock()
    children = {}

    def read():
        return json.loads(index.read_text('utf-8')) if index.exists() else []

    def summary(profile):
        result = dict(profile, student_id=None, schoolSessionSaved=False, wechatSaved=False,
                      locationSaved=False, verifiedAt=None, accessExpiresAt=None, ready=False)
        path = directory / profile['id']
        if not path.is_dir():
            return result
        local = LocalStore(path)
        saved = local.session()
        if saved:
            result.update(student_id=saved['student_id'], schoolSessionSaved=True)
        result['locationSaved'] = bool(local.location())
        authorization = path / 'wechat.enc'
        if authorization.exists():
            value = local.vault.open(authorization.read_bytes(), 'wechat-authorization')
            if saved and value.get('student_id') == saved['student_id']:
                result.update(wechatSaved=True, verifiedAt=value.get('last_verified_at'),
                              accessExpiresAt=value.get('credentials', {}).get('expires_at'))
        result['ready'] = bool(result['schoolSessionSaved'] and result['wechatSaved'] and
                               result['locationSaved'] and profile.get('saved', True))
        return result

    @app.get('/accounts')
    def accounts_page():
        return send_from_directory(root / 'static', 'accounts.html')

    @app.get('/api/accounts')
    def account_list():
        with lock:
            return jsonify(profiles=[summary(p) for p in read()], schedulingEnabled=False)

    @app.post('/api/accounts')
    def account_create():
        value = request.get_json(silent=True)
        title = value.get('name', '') if isinstance(value, dict) else ''
        if not isinstance(title, str) or not title.strip() or len(title) > 80:
            return jsonify(error='请输入不超过 80 字的账号备注。'), 400
        with lock:
            profiles = read()
            if len(profiles) >= 20:
                return jsonify(error='本机最多保存 20 个授权配置。'), 400
            profile = {'id': uuid.uuid4().hex, 'name': title.strip(), 'saved': False}
            profiles.append(profile)
            temp = directory / 'index.new'
            temp.write_text(json.dumps(profiles, ensure_ascii=False), encoding='utf-8')
            temp.replace(index)
            return jsonify(profile=profile), 201

    @app.post('/api/accounts/<profile>/save')
    def profile_save(profile):
        value = request.get_json(silent=True)
        name = value.get('name', '') if isinstance(value, dict) else ''
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            return jsonify(error='请输入不超过 80 字的账号备注。'), 400
        with lock:
            profiles = read()
            target = next((p for p in profiles if p['id'] == profile), None)
            if not target:
                return jsonify(error='账号草稿不存在。'), 404
            child = children.get(profile)
            if child:
                login = child.extensions['browser_login']
                if child.extensions['wechat_authorization'].status()['active'] or (login.thread and login.thread.is_alive()):
                    return jsonify(error='请先完成当前学校登录或微信授权。'), 409
            record = summary(target)
            if not all(record[k] for k in ('schoolSessionSaved', 'wechatSaved', 'locationSaved')):
                return jsonify(error='请先完成学校登录、微信授权和位置保存，再添加到账号库。'), 400
            if target.get('saved') is False and not record.get('verifiedAt'):
                return jsonify(error='请先完成账号一致性核对和成功取票，再保存新账号。'), 400
            target.update(name=name.strip(), saved=True, updated_at=time.time())
            temp = directory / 'index.new'
            temp.write_text(json.dumps(profiles, ensure_ascii=False), encoding='utf-8')
            temp.replace(index)
            return jsonify(profile=summary(target), ok=True)

    @app.post('/api/accounts/import-current')
    def import_current_account():
        with lock, store.lock:
            saved = store.session()
            if not saved:
                return jsonify(error='当前电脑页面没有保存学校账号。'), 400
            profiles = read()
            for profile in profiles:
                if summary(profile).get('student_id') == saved['student_id']:
                    return jsonify(profile=profile, existing=True)
            if len(profiles) >= 20:
                return jsonify(error='本机最多保存 20 个授权配置。'), 400
            profile = {'id': uuid.uuid4().hex, 'name': '当前账号 ' + saved['student_id']}
            target = LocalStore(directory / profile['id'])
            target.save_session({k:v for k,v in saved.items() if not k.startswith('operation_ticket')})
            if store.location():
                target.save_location(store.location())
            credentials = store.directory / 'wechat.enc'
            if credentials.exists():
                value = store.vault.open(credentials.read_bytes(), 'wechat-authorization')
                if value.get('student_id') == saved['student_id']:
                    (target.directory / 'wechat.enc').write_bytes(target.vault.seal(value, 'wechat-authorization'))
            profiles.append(profile)
            temp = directory / 'index.new'
            temp.write_text(json.dumps(profiles, ensure_ascii=False), encoding='utf-8')
            temp.replace(index)
            return jsonify(profile=profile, existing=False), 201

    @app.route('/api/accounts/<profile>/<path:action>', methods=['GET', 'POST'])
    def profile_proxy(profile, action):
        if not re.fullmatch(r'[a-f0-9]{32}', profile) or action not in ALLOWED:
            return jsonify(error='不存在的授权配置或不允许的操作。'), 404
        with lock:
            if not any(item['id'] == profile for item in read()):
                return jsonify(error='不存在的授权配置。'), 404
            if profile not in children:
                child = factory(directory / profile, profiles_enabled=False)
                child.config.update(SESSION_COOKIE_NAME='account_' + profile,
                                    SESSION_COOKIE_PATH='/api/accounts/' + profile)
                children[profile] = child
            child = children[profile]
        environ = dict(request.environ)
        environ['PATH_INFO'] = '/api/' + action
        environ['SCRIPT_NAME'] = ''
        return Response.from_app(child, environ)

    app.extensions['account_children'] = children
