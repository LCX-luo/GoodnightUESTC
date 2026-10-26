import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import create_app
from browser_login import BrowserLogin
from core import (LocalStore, ReadOnlyTransport, ReadOnlySchool, ToolError,
                  allowed_read, browser_allowed, normalize_location, offline_test, online_test,
                  ORIGIN, now)

BASE = 'http://127.0.0.1:8090'
SNAPSHOT = {'student_id': '202300000001', 'saved_at': 123,
            'user_agent': 'Synthetic Test Browser', 'cookies': [
                {'name': 'SESSION', 'value': 'synthetic-cookie-secret', 'domain': 'jzsz.uestc.edu.cn',
                 'path': '/', 'expires': -1, 'secure': True, 'httpOnly': True}]}
POINT = {'name': '测试位置', 'latitude': 30.7528, 'longitude': 103.9313, 'coordinate_system': 'wgs84'}


class GuardTests(unittest.TestCase):
    def test_today_uses_existing_authorization_and_reenters_only_when_expired(self):
        from unittest.mock import MagicMock
        from core import read_today, AuthRequired
        school = MagicMock()
        school.today.return_value = {'recordStatusCode': 'PENDING'}
        self.assertEqual(read_today(school), school.today.return_value)
        school.enter.assert_not_called()
        school.today.side_effect = AuthRequired('session_rejected')
        read_today(school)
        school.enter.assert_called_once()

    def test_every_business_write_is_denied_before_network(self):
        transport = ReadOnlyTransport(SNAPSHOT)
        with patch('core.Transport.request', side_effect=AssertionError('network must not run')):
            for method in ('POST', 'PATCH', 'PUT', 'DELETE', 'GET'):
                for path in ('/student-checkin-record/checkin', '/student-checkin-record/report', '/unknown'):
                    with self.subTest(method=method, path=path), self.assertRaises(ToolError) as error:
                        transport.request(method, ORIGIN+'/daily-checkin/api'+path, stage='test')
                    self.assertEqual(error.exception.reason, 'write_blocked')

    def test_get_with_body_is_denied(self):
        with self.assertRaises(ToolError):
            ReadOnlyTransport(SNAPSHOT).request('GET', ORIGIN+'/', payload={}, stage='test')

    def test_direct_submit_is_disabled(self):
        with self.assertRaises(ToolError):
            ReadOnlySchool(None, {}, None).submit({})

    def test_only_https_school_allowlist_can_be_read(self):
        self.assertTrue(allowed_read('GET', ORIGIN+'/daily-checkin/api/student-checkin-record/today'))
        for url in ('http://jzsz.uestc.edu.cn/', 'https://evil.example/', ORIGIN+':8443/',
                    'https://user:pass@jzsz.uestc.edu.cn/', ORIGIN+'/anything'):
            self.assertFalse(allowed_read('GET', url))

    def test_browser_allows_authentication_and_blocks_attendance(self):
        self.assertTrue(browser_allowed('POST', 'https://idas.uestc.edu.cn/authserver/login'))
        self.assertTrue(browser_allowed('POST', 'https://idas.uestc.edu.cn/authserver/reAuthCheck/verify.do'))
        self.assertTrue(browser_allowed('GET', ORIGIN+'/daily-checkin/checkLogin?appId=294'))
        for method in ('GET', 'POST', 'PUT'):
            self.assertFalse(browser_allowed(method, ORIGIN+'/daily-checkin/api/student-checkin-record/checkin'))
        self.assertFalse(browser_allowed('POST', 'https://evil.example/upload'))

    def test_offline_never_calls_network(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('no network')):
            result = offline_test(POINT)
        self.assertTrue(result['passed'])
        self.assertEqual(result['schoolRequests'], 0)
        self.assertEqual(len(result['blockedRequests']), 3)

    def test_coordinate_conversion_and_rejection(self):
        value = normalize_location(POINT)
        self.assertNotAlmostEqual(value['latitude'], value['gcj02']['latitude'], places=5)
        gcj = normalize_location({**POINT, 'coordinate_system': 'gcj02'})
        self.assertEqual(gcj['latitude'], gcj['gcj02']['latitude'])
        for bad in (float('nan'), float('inf'), 91):
            with self.assertRaises(ToolError):
                normalize_location({**POINT, 'latitude': bad})

    def test_online_uses_get_only_and_returns_no_raw_personal_record(self):
        from moonuestc.transport import Response
        calls = []
        def respond(transport, method, url, *, stage, **kwargs):
            self.assertTrue(allowed_read(method, url))
            calls.append((method, url))
            if stage == 'portal_warmup':
                body = {'code': 0}
            elif stage == 'micro_app_entry':
                return Response(200, {}, b'', ORIGIN+'/daily-checkin-h5/index.html?appId=294')
            elif stage == 'today':
                body = {'code': 0, 'data': {'businessDate': now().date().isoformat(),
                    'recordStatusCode': 'PENDING', 'abnormalFlag': False, 'name': 'private-person'}}
            elif stage == 'schedule':
                body = {'code': 0, 'data': {'effective': True,
                    'studentCheckinStartOffsetMinute': 1260, 'studentCheckinEndOffsetMinute': 1410}}
            elif stage == 'locations':
                body = {'code': 0, 'data': [{**normalize_location(POINT)['gcj02'], 'radiusMeter': 200}]}
            else:
                raise AssertionError(stage)
            return Response(200, {}, json.dumps(body).encode(), url)
        with patch('core.Transport.request', new=respond):
            result = online_test(SNAPSHOT, POINT)
        self.assertEqual(len(calls), 3)
        self.assertTrue(result['insideFence'])
        self.assertEqual(result['schoolWrites'], 0)
        self.assertNotIn('private-person', json.dumps(result))


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name)
        self.client = self.app.test_client()
        self.status = self.client.get('/api/status', base_url=BASE).json
        self.headers = {'Origin': BASE, 'X-CSRF-Token': self.status['csrf']}

    def tearDown(self):
        self.temp.cleanup()

    def post(self, path, value):
        return self.client.post(path, json=value, base_url=BASE, headers=self.headers)

    def test_cookie_is_encrypted_and_never_in_public_status(self):
        store = self.app.extensions['local_store']
        store.save_session(SNAPSHOT)
        blob = (Path(self.temp.name)/'session.enc').read_bytes()
        self.assertNotIn(b'synthetic-cookie-secret', blob)
        self.assertEqual(store.session(), SNAPSHOT)
        state = self.client.get('/api/status', base_url=BASE).json
        self.assertEqual(state['account']['cookie_count'], 1)
        self.assertNotIn('synthetic-cookie-secret', json.dumps(state))

    def test_tampered_cookie_rejected(self):
        store = self.app.extensions['local_store']
        store.save_session(SNAPSHOT)
        path = Path(self.temp.name)/'session.enc'
        path.write_bytes(path.read_bytes()[:-1]+b'x')
        with self.assertRaises(ToolError):
            store.session()

    def test_cross_origin_and_missing_csrf_denied(self):
        self.assertEqual(self.client.post('/api/test/offline', json={}, base_url=BASE).status_code, 403)
        self.assertEqual(self.client.post('/api/test/offline', json={}, base_url=BASE,
                                         headers={**self.headers, 'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/status', base_url='http://evil.example').status_code, 403)

    def test_save_location_and_offline_check(self):
        self.assertEqual(self.post('/api/location', POINT).status_code, 200)
        result = self.post('/api/test/offline', {}).json['result']
        self.assertTrue(result['passed'])
        self.assertFalse(result['submitted'])

    def test_online_requires_imported_session(self):
        self.assertEqual(self.post('/api/test/online', {}).status_code, 400)

    def test_submit_requires_explicit_confirmation(self):
        self.assertEqual(self.post('/api/checkin', {}).status_code, 400)
        self.assertTrue(self.status['schoolWritesEnabled'])

    def test_forget_removes_local_session(self):
        store = self.app.extensions['local_store']
        store.save_session(SNAPSHOT)
        self.assertEqual(self.post('/api/session/forget', {}).status_code, 200)
        self.assertIsNone(store.session())


class LoginTests(unittest.TestCase):
    def test_browser_session_is_saved_only_after_verified_read(self):
        with tempfile.TemporaryDirectory() as directory, patch('playwright.sync_api.sync_playwright') as playwright, patch('browser_login.NETWORK.browser_options', return_value={}):
            from unittest.mock import MagicMock
            store = LocalStore(directory)
            manager = BrowserLogin(store)
            context = playwright.return_value.__enter__.return_value.chromium.launch_persistent_context.return_value
            context.cookies.return_value = SNAPSHOT['cookies']
            page = context.new_page.return_value
            page.url = 'https://jzsz.uestc.edu.cn/'
            page.is_closed.return_value = False
            page.evaluate.return_value = SNAPSHOT['user_agent']
            with patch('browser_login.verify_session', return_value=None) as verify:
                manager.run(SNAPSHOT['student_id'], 'synthetic-password-not-to-save')
            verify.assert_called_once()
            self.assertEqual(manager.status()['state'], 'success')
            self.assertEqual(store.session()['cookies'], SNAPSHOT['cookies'])
            self.assertNotIn('password', store.session())
            context.close.assert_called_once()

    def test_browser_uses_private_profile_and_artifacts_without_changing_process_temp(self):
        import os
        with tempfile.TemporaryDirectory() as directory, patch('playwright.sync_api.sync_playwright') as playwright, patch('browser_login.NETWORK.browser_options', return_value={}):
            store = LocalStore(directory); manager = BrowserLogin(store)
            launch = playwright.return_value.__enter__.return_value.chromium.launch_persistent_context
            launch.side_effect = PermissionError('sensitive-path-or-url-must-not-be-returned')
            original = (os.environ.get('TEMP'), os.environ.get('TMP'))
            manager.run(SNAPSHOT['student_id'], 'synthetic-password')
            call = launch.call_args
            profile = Path(call.args[0]); artifacts = Path(call.kwargs['artifacts_dir'])
            self.assertEqual(profile.parent, artifacts.parent)
            self.assertTrue(profile.is_relative_to(Path(directory)))
            self.assertEqual(call.kwargs['env']['TEMP'], str(profile.parent))
            self.assertEqual(call.kwargs['env']['TMP'], str(profile.parent))
            self.assertEqual(original, (os.environ.get('TEMP'), os.environ.get('TMP')))
            self.assertEqual(manager.status()['reason'], 'browser_temp_permission')
            self.assertNotIn('sensitive', str(manager.status()))
            self.assertIsNone(store.session())

    def test_cancel_during_verification_does_not_save_session(self):
        with tempfile.TemporaryDirectory() as directory, patch('playwright.sync_api.sync_playwright') as playwright, patch('browser_login.NETWORK.browser_options', return_value={}):
            store = LocalStore(directory)
            manager = BrowserLogin(store)
            context = playwright.return_value.__enter__.return_value.chromium.launch_persistent_context.return_value
            context.cookies.return_value = SNAPSHOT['cookies']
            context.new_page.return_value.is_closed.return_value = False
            context.new_page.return_value.url = 'https://jzsz.uestc.edu.cn/'
            context.new_page.return_value.evaluate.return_value = SNAPSHOT['user_agent']
            with patch('browser_login.verify_session', side_effect=lambda *args: manager.cancel()):
                manager.run(SNAPSHOT['student_id'], 'synthetic-password')
            self.assertEqual(manager.status()['state'], 'cancelled')
            self.assertIsNone(store.session())


class ProgressTests(unittest.TestCase):
    def test_progress_finishes_even_after_error(self):
        from progress import Progress
        progress = Progress()
        with self.assertRaises(ValueError):
            with progress.operation('prepare'):
                progress.step('正在查询地址')
                self.assertTrue(progress.snapshot()['active'])
                self.assertEqual(progress.snapshot()['message'], '正在查询地址')
                raise ValueError('synthetic error')
        self.assertFalse(progress.snapshot()['active'])


if __name__ == '__main__':
    unittest.main()
