"""Run explicitly with the isolated Python 3.13 runtime; no live networking."""
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx2
from pydantic import SecretStr
from moon_uestc.client import AuthService
from moon_uestc.models import APIResponse, UserInfo
from moon_uestc.wechat_models import WeChatCredentials
from wechat_worker import run

STUDENT = '202300000001'
CREDENTIALS = {'openid': 'synthetic-openid', 'access_token': 'synthetic-access',
               'refresh_token': 'synthetic-refresh', 'expires_at': int(time.time()) + 3600}


class WorkerProtocol(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.codes = []
        self.mismatch = False
        self.events = []
        self.wx = MagicMock()
        self.wx.__enter__.return_value = self.wx
        self.wx.get_code.side_effect = [SecretStr('login-code'), SecretStr('ticket-code')]
        self.config = {'student_id': STUDENT, 'session': 'h5-session', 'credentials': CREDENTIALS,
                       'allow_qr': False}

    def response(self, request):
        path = request.url.path
        self.calls.append(path)
        if path.endswith('/user-info'):
            mini = path.startswith('/platform-app/')
            self.assertEqual(request.headers['platform'], 'mp-weixin' if mini else 'h5')
            self.assertEqual(request.headers['cookie'], 'SESSION=mini-session' if mini else 'SESSION=h5-session')
            user = {'id': 'different' if mini and self.mismatch else 'own-id',
                    'username': STUDENT, 'fullName': 'Synthetic', 'role': '001', 'roleName': '学生'}
            return httpx2.Response(200, json={'ok': True, 'code': 0, 'data': {'userData': user}})
        self.assertEqual(request.headers['platform'], 'mp-weixin')
        self.codes.append(json.loads(request.content)['code'])
        if path.endswith('/check-bind'):
            self.assertNotIn('cookie', request.headers)
            return httpx2.Response(200, json={'ok': True, 'data': {'bind': True, 'sessionId': 'mini-session'}})
        if path.endswith('/checkin-ticket'):
            self.assertEqual(request.headers['cookie'], 'SESSION=mini-session')
            return httpx2.Response(200, json={'ok': True, 'data': {'ticket': 't' * 43}})
        self.fail('Unexpected request: ' + path)

    def execute(self):
        def record(event, **values):
            self.events.append({'event': event, **values})
        with patch('httpx2.HTTPTransport', side_effect=lambda **kw: httpx2.MockTransport(self.response)), \
                patch('moon_uestc.WeChatClient', return_value=self.wx), patch('wechat_worker.emit', side_effect=record):
            run(self.config)

    def test_two_fresh_codes_and_separate_sessions_without_attendance_write(self):
        self.execute()
        self.assertEqual(self.codes, ['login-code', 'ticket-code'])
        self.assertEqual(len(self.calls), 4)
        complete = self.events[-1]
        self.assertEqual(complete['event'], 'complete')
        self.assertFalse(complete['submitted'])
        self.assertEqual(len(complete['ticket']), 43)

    def test_identity_mismatch_stops_before_second_code_and_ticket(self):
        self.mismatch = True
        with self.assertRaisesRegex(RuntimeError, '^wechat_identity_mismatch$'):
            self.execute()
        self.assertEqual(self.codes, ['login-code'])
        self.assertEqual(self.wx.get_code.call_count, 1)
        self.assertFalse(any(e['event'] == 'complete' for e in self.events))

    def test_write_guard_blocks_even_accidental_sdk_business_call(self):
        def accidental_write(auth):
            return auth._http.request('POST', '/api/student-checkin-record/checkin', APIResponse[UserInfo])
        with patch.object(AuthService, 'user_info', accidental_write):
            with self.assertRaisesRegex(RuntimeError, '^school_request_blocked$'):
                self.execute()
        self.assertEqual(self.calls, [])

    def test_no_cached_authorization_does_not_start_qr_in_silent_mode(self):
        self.config['credentials'] = None
        with self.assertRaisesRegex(RuntimeError, '^wechat_authorization_required$'):
            self.execute()
        self.wx.create_qr.assert_not_called()
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
