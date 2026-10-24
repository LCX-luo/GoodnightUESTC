import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core import LocalStore, ToolError
from wechat_auth import WeChatAuthorization, school_session

SNAPSHOT = {'student_id': '202300000001', 'saved_at': 123,
            'user_agent': 'Synthetic', 'cookies': [
                {'name': 'SESSION', 'value': 'school-secret', 'domain': 'jzsz.uestc.edu.cn',
                 'path': '/', 'expires': -1}]}
TOKEN = {'openid': 'own-id', 'access_token': 'access-secret', 'refresh_token': 'refresh-secret',
         'expires_at': 2000000000}


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LocalStore(self.temp.name)
        self.store.save_session(SNAPSHOT)
        self.auth = WeChatAuthorization(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def worker(self, events):
        proc = MagicMock()
        proc.stdin = io.StringIO()
        proc.stdout = io.StringIO(''.join(json.dumps(e) + '\n' for e in events))
        proc.wait.return_value = 0
        proc.poll.return_value = 0
        return proc

    def complete(self, **changes):
        return {'event': 'complete', 'ticket': 't' * 43, 'student_id': SNAPSHOT['student_id'],
                'submitted': False, 'code_lengths': [32, 32], **changes}

    def test_credentials_and_ticket_encrypted_without_status_leak(self):
        proc = self.worker([{'event': 'credentials', 'credentials': TOKEN}, self.complete()])
        with patch('wechat_auth.subprocess.Popen', return_value=proc):
            saved = self.auth.execute(SNAPSHOT, allow_qr=True)
        self.assertEqual(saved['operation_ticket'], 't' * 43)
        self.assertEqual(self.auth.cached(SNAPSHOT), TOKEN)
        for filename in ('wechat.enc', 'session.enc'):
            raw = (Path(self.temp.name) / filename).read_bytes()
            self.assertNotIn(b'access-secret', raw)
            self.assertNotIn(b't' * 43, raw)
        status = json.dumps(self.auth.status())
        for secret in ('school-secret', 'access-secret', 'refresh-secret', 't' * 43):
            self.assertNotIn(secret, status)
        self.assertTrue(self.auth.status()['ticketReady'])
        self.assertFalse(self.auth.status()['submitted'])
        self.assertIsNone(self.auth.cached({**SNAPSHOT, 'student_id': 'other'}))

    def test_wrong_identity_or_unexpected_submit_cannot_install_ticket(self):
        for changes in ({'student_id': 'other'}, {'submitted': True}, {'ticket': 'invalid'}):
            with self.subTest(changes=changes):
                proc = self.worker([self.complete(**changes)])
                with patch('wechat_auth.subprocess.Popen', return_value=proc), self.assertRaises(ToolError):
                    self.auth.execute(SNAPSHOT, allow_qr=True)
                self.assertNotIn('operation_ticket', self.store.session())

    def test_browser_account_change_invalidates_authorization(self):
        self.store.save_session({**SNAPSHOT, 'saved_at': 456})
        proc = self.worker([self.complete()])
        with patch('wechat_auth.subprocess.Popen', return_value=proc), self.assertRaises(ToolError) as error:
            self.auth.execute(SNAPSHOT, allow_qr=True)
        self.assertEqual(error.exception.reason, 'wechat_account_changed')
        self.assertNotIn('operation_ticket', self.store.session())

    def test_local_consumption_removes_ticket_but_keeps_login(self):
        self.store.save_session({**SNAPSHOT, 'operation_ticket': 't' * 43,
                                 'operation_ticket_expires_at': 2000000000})
        self.auth.consume_local_ticket()
        self.assertNotIn('operation_ticket', self.store.session())
        self.assertEqual(self.store.session()['cookies'], SNAPSHOT['cookies'])

    def test_ambiguous_school_sessions_are_not_guessed(self):
        self.assertEqual(school_session(SNAPSHOT), 'school-secret')
        ambiguous = {**SNAPSHOT, 'cookies': SNAPSHOT['cookies'] + [
            {**SNAPSHOT['cookies'][0], 'value': 'second', 'path': '/daily-checkin'}]}
        with self.assertRaises(ToolError):
            school_session(ambiguous)

    def test_silent_mode_requires_authorization_before_launch(self):
        with patch('wechat_auth.subprocess.Popen') as launch, self.assertRaises(ToolError):
            self.auth.execute(SNAPSHOT, allow_qr=False)
        launch.assert_not_called()
