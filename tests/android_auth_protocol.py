"""Desktop mock validation of the APK Python adapter; no network requests."""
import importlib.util
import json
from pathlib import Path
import ssl
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'android/app/build/generated/wechatPython'))
try:
    import certifi
except ImportError:
    sys.modules['certifi'] = types.SimpleNamespace(where=lambda: None)
spec = importlib.util.spec_from_file_location('phone_auth', ROOT / 'android/app/src/main/python/native_auth.py')
phone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phone)


class PhoneProtocol(unittest.TestCase):
    def test_signing_matches_verified_sdk_byte_for_byte(self):
        from moon_uestc._wechat_login import LoginClient
        client = MagicMock()
        client.request.return_value = (200, {}, b'{"code":0}')
        body = {'extInfo': {'listI': {'user_type': {'value': [0]}}}}
        with patch.object(phone.time, 'time', return_value=1700000000), patch.object(phone.secrets, 'randbelow', return_value=1234):
            phone.signed(client, 'operation', body)
        call = client.request.call_args.args
        data, headers = call[2:4]
        self.assertEqual(headers, LoginClient._signed_headers(data, '1700000000000', '1234'))

    def execute(self, mismatch=False):
        client = MagicMock()
        user = {'id': 'own-id', 'username': 'synthetic'}
        mini = {'id': 'another' if mismatch else 'own-id', 'username': 'synthetic'}
        client.school.side_effect = [ {'userData': user}, {'bind':True,'sessionId':'mini-session'},
                                    {'userData':mini}, {'ticket':'t'*43} ]
        callback = MagicMock();callback.cancelled.return_value = False
        credentials = {'school_user_id':'own-id','openid':'own-openid','access_token':'own-access',
                       'refresh_token':'own-refresh','expires_at':2000000000}
        with patch.object(phone, 'Client', return_value=client), patch.object(phone, 'login_buffer', return_value='buffer'), \
                patch.object(phone, 'get_code', side_effect=['login-code','ticket-code']) as codes:
            if mismatch:
                with self.assertRaisesRegex(RuntimeError, 'identity_mismatch'):
                    phone.acquire('h5-session', json.dumps(credentials), callback, False)
                self.assertEqual(codes.call_count, 1)
            else:
                result = json.loads(phone.acquire('h5-session',json.dumps(credentials),callback,False))
                self.assertEqual(result['ticket'], 't'*43)
                calls = client.school.call_args_list
                self.assertEqual(calls[0].args[2], 'h5-session')
                self.assertEqual(calls[1].kwargs['body']['code'],'login-code')
                self.assertEqual(calls[2].args[2], 'mini-session')
                self.assertEqual(calls[3].args[2], 'mini-session')
                self.assertEqual(calls[3].args[3]['code'],'ticket-code')

    def test_two_codes_and_separate_school_sessions(self):
        self.execute()

    def test_wrong_identity_stops_before_ticket(self):
        self.execute(mismatch=True)

    def test_school_write_and_untrusted_host_blocked_before_network(self):
        client = phone.Client()
        with patch.object(client.opener, 'open') as network:
            for method,url in [('POST',phone.SCHOOL+'/daily-checkin/api/student-checkin-record/checkin'),
                               ('GET','https://evil.example/'),('GET','http://jzsz.uestc.edu.cn/')]:
                with self.assertRaisesRegex(RuntimeError,'request_blocked'):
                    client.request(method,url)
            network.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
