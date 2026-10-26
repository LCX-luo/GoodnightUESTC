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
    def poll(self, responses):
        client, callback = MagicMock(), MagicMock()
        client.request.side_effect = responses
        callback.cancelled.return_value = False
        return client, callback

    def test_network_diagnostics_keep_endpoint_and_nested_dns_without_secrets(self):
        callback=MagicMock()
        client=phone.Client(callback)
        error=phone.urllib.error.URLError(phone.socket.gaierror(-2, 'secret token and private URL'))
        with patch.object(client.opener,'open',side_effect=error):
            with self.assertRaises(phone.urllib.error.URLError):
                client.request('GET',phone.OAUTH+'?secret=must-not-export')
        logs='\n'.join(c.args[0] for c in callback.diagnostic.call_args_list)
        self.assertIn('ep=qr_create',logs)
        self.assertIn('type=gaierror errno=-2',logs)
        self.assertNotIn('must-not-export',logs)
        self.assertNotIn('secret token',logs)
        self.assertNotIn('https://',logs)

    def test_refresh_rejection_logs_only_business_code(self):
        callback=MagicMock();client=phone.Client(callback)
        with patch.object(client,'request',return_value=(200,{},b'{"code":-109,"secret":"do-not-export"}')):
            with self.assertRaisesRegex(RuntimeError,'wechat_credential_rejected'):
                phone.signed(client,'pcyyb_refresh_token_auth',{})
        self.assertIn('net_business code=-109',[c.args[0] for c in callback.diagnostic.call_args_list])
        self.assertNotIn('do-not-export',str(callback.diagnostic.call_args_list))

    def test_transient_disconnect_reuses_same_qr_then_authorizes(self):
        client, callback = self.poll([phone.http.client.RemoteDisconnected('sensitive URL must not escape'),
                                     (200, {}, b"window.wx_errcode=405;window.wx_code='synthetic-code';")])
        with patch.object(phone.time, 'sleep'):
            self.assertEqual(phone.wait_for_qr(client, 'same-uuid', callback), 'synthetic-code')
        uuids = [phone.urllib.parse.parse_qs(phone.urllib.parse.urlsplit(c.args[1]).query)['uuid']
                 for c in client.request.call_args_list]
        self.assertEqual(uuids, [['same-uuid'], ['same-uuid']])
        callback.diagnostic.assert_any_call('qr_remote_disconnected')
        callback.diagnostic.assert_any_call('qr_poll_authorized')

    def test_http_429_is_explicit_and_never_retried(self):
        client, callback = self.poll([(429, {}, b'private server content')])
        with self.assertRaisesRegex(RuntimeError, '^qr_http_429$'):
            phone.wait_for_qr(client, 'same-uuid', callback)
        self.assertEqual(client.request.call_count, 1)

    def test_disconnect_retries_are_bounded_to_three(self):
        client, callback = self.poll([ConnectionResetError('secret')] * 5)
        with patch.object(phone.time, 'sleep'), self.assertRaisesRegex(RuntimeError, '^qr_connection_failed$'):
            phone.wait_for_qr(client, 'same-uuid', callback)
        self.assertEqual(client.request.call_count, 4)

    def test_tls_verification_failure_is_fatal_without_retry(self):
        error = phone.urllib.error.URLError(ssl.SSLCertVerificationError(1, 'private host'))
        client, callback = self.poll([error])
        with self.assertRaisesRegex(RuntimeError, '^qr_tls_certificate$'):
            phone.wait_for_qr(client, 'same-uuid', callback)
        self.assertEqual(client.request.call_count, 1)
        context = phone.Client().opener
        ssl_handler = next(handler for handler in context.handlers if isinstance(handler, phone.urllib.request.HTTPSHandler))
        self.assertEqual(ssl_handler._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ssl_handler._context.check_hostname)

    def test_read_exception_classification_and_unknown_bridge_error_are_redacted(self):
        for error, code in [(phone.http.client.IncompleteRead(b'secret'), 'qr_incomplete_read'),
                            (phone.http.client.BadStatusLine('secret'), 'qr_bad_status_line'),
                            (UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'secret'), 'qr_response_encoding')]:
            with self.subTest(code=code):
                self.assertEqual(phone.poll_failure(error)[0], code)
        with patch.object(phone, '_acquire', side_effect=ValueError('secret-token-and-URL')):
            with self.assertRaisesRegex(RuntimeError, '^python_failure_valueerror$'):
                phone.acquire('unused', '', MagicMock(), True)
        with patch.object(phone, '_acquire', side_effect=ConnectionResetError(104, 'secret-token-and-URL')):
            with self.assertRaisesRegex(RuntimeError, '^python_failure_connectionreseterror_errno_104$'):
                phone.acquire('unused', '', MagicMock(), True)

    def test_poll_statuses_match_sdk_and_unknown_is_not_silently_pending(self):
        for status in (404, 408):
            self.assertEqual(phone.poll_result(f'window.wx_errcode={status};'.encode()), (status, None))
        self.assertEqual(phone.poll_result(b"window.wx_errcode=405;window.wx_code='synthetic-code';"),
                         (405, 'synthetic-code'))
        for body, reason in [(b'window.wx_errcode=403;', 'cancelled'),
                             (b'window.wx_errcode=402;', 'qr_expired'),
                             (b'window.wx_errcode=500;', 'qr_status_unrecognized'),
                             (b'window.wx_errcode=405;', 'qr_unavailable')]:
            with self.subTest(reason=reason), self.assertRaisesRegex(RuntimeError, reason):
                phone.poll_result(body)

    def test_scan_timeout_then_confirmation_keeps_login_type_in_callback(self):
        client, exchange, callback = MagicMock(), MagicMock(), MagicMock()
        callback.cancelled.return_value = False
        user = {'id': 'own-id', 'username': 'synthetic'}
        client.school.side_effect = [{'userData': user}, {'bind': True, 'sessionId': 'mini'},
                                    {'userData': user}, {'ticket': 't' * 43}]
        client.request.side_effect = [(200, {}, b'<img src="/connect/qrcode/test-uuid">'),
                                     (200, {}, b'fake-image'), TimeoutError(),
                                     (200, {}, b'window.wx_errcode=404;'),
                                     (200, {}, b"window.wx_errcode=405;window.wx_code='fake-code';")]
        exchange.request.return_value = (302, {}, b'')
        exchange.cookies = [types.SimpleNamespace(name=k, value=v, domain='yybadaccess.3g.qq.com', path='/')
                            for k, v in {'openid': 'own', 'accesstoken': 'access', 'refreshtoken': 'refresh'}.items()]
        with patch.object(phone, 'Client', side_effect=[client, exchange]), \
                patch.object(phone, 'login_buffer', return_value='buffer'), \
                patch.object(phone, 'get_code', side_effect=['first', 'second']), patch.object(phone.time, 'sleep'):
            result = json.loads(phone.acquire('school-session', '', callback, True))
        query = phone.urllib.parse.parse_qs(phone.urllib.parse.urlsplit(exchange.request.call_args.args[1]).query)
        self.assertEqual(query['login_type'], ['WX'])
        self.assertEqual(query['code'], ['fake-code'])
        self.assertEqual(result['ticket'], 't' * 43)
        callback.credentials.assert_called_once()

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
