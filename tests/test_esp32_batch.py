"""Host-only GN1 batch CLI tests. Serial and all device responses are fake."""
import base64
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import types
import unittest
from unittest.mock import patch
from esp32 import provision


def frame(**values):
    return b'GN1 ' + json.dumps(values).encode() + b'\n'


class FakeSerial:
    def __init__(self, responses):
        self.responses = list(responses)
        self.writes = bytearray()
        self.closed = False
        self.reads = 0
    def open(self): pass
    def reset_input_buffer(self): pass
    def flush(self): pass
    def close(self): self.closed = True
    def write(self, data): self.writes.extend(data)
    def readline(self):
        self.reads += 1
        if not self.responses:
            raise AssertionError('CLI waited beyond final fake device response')
        return self.responses.pop(0)
    def request(self):
        self.assert_single_frame()
        return json.loads(base64.b64decode(bytes(self.writes)[4:].strip()))
    def assert_single_frame(self):
        if self.writes.count(b'\n') != 1:
            raise AssertionError('Expected exactly one GN1 USB request, with no replay')


class BatchTests(unittest.TestCase):
    def run_cli(self, args, responses):
        serial = FakeSerial(responses)
        output = io.StringIO()
        with patch.dict('sys.modules', {'serial': types.SimpleNamespace(Serial=lambda: serial)}), patch('sys.argv', ['provision.py', '--port', 'FAKE', *args]), patch('esp32.provision.time.sleep'), redirect_stdout(output):
            provision.main()
        return serial, [json.loads(line) for line in output.getvalue().splitlines()]

    def test_batch_continues_after_first_account_error_and_second_success(self):
        serial, events = self.run_cli(['batch'], [
            frame(state='batch_queued'),
            frame(state='oauth_rejected', account='synthetic-account-a', code=401),
            frame(state='authorization_verified', account='synthetic-account-b'),
            frame(state='batch_completed'),
        ])
        self.assertEqual(serial.reads, 4)
        self.assertEqual(events[-1]['state'], 'batch_completed')
        self.assertEqual(events[1]['code'], 401)
        self.assertEqual(serial.request(), {'op': 'batch', 'submit': False})
        self.assertTrue(serial.closed)

    def test_batch_submit_sends_one_request_without_configuration_or_schedule_change(self):
        serial, events = self.run_cli(['batch', '--submit-once'], [
            frame(state='request_rejected', account='synthetic-account-a', code=46002),
            frame(state='existing_record_only', account='synthetic-account-a'),
            frame(state='checkin_confirmed', account='synthetic-account-b'),
            frame(state='batch_completed', sensitive_payload='must-not-be-printed'),
        ])
        self.assertEqual(serial.reads, 4)
        self.assertEqual(serial.request(), {'op': 'batch', 'submit': True})
        self.assertNotIn('sensitive_payload', events[-1])
        self.assertNotIn('config', serial.request())
        self.assertNotIn('enabled', serial.request())

    def test_probe_still_stops_on_its_own_error(self):
        serial, events = self.run_cli(['probe', '--account', 'synthetic-account-a'], [
            frame(state='oauth_rejected', account='synthetic-account-a', code=401),
            frame(state='batch_completed'),
        ])
        self.assertEqual(serial.reads, 1)
        self.assertEqual(events[-1]['state'], 'oauth_rejected')
        self.assertEqual(serial.request(), {'op': 'probe', 'account': 'synthetic-account-a', 'submit': False})

    def test_batch_refuses_ambiguous_account_filter_before_opening_serial(self):
        with patch('sys.argv', ['provision.py', 'batch', '--account', 'synthetic-account-a']), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            provision.main()


if __name__ == '__main__':
    unittest.main()
