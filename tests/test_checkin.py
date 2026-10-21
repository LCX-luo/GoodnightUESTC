"""Manual submission tests use synthetic school responses only."""
import datetime as dt
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch
from app import create_app
from checkin import Attempts, SubmissionTransport, SUBMIT_URL, prepare_checkin, submit_checkin
from core import ToolError, normalize_location
from test_readonly import SNAPSHOT, POINT, BASE

INSTANT = dt.datetime(2026, 10, 21, 22, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))
DAY = '2026-10-21'
SCHEDULE = {'effective': True, 'studentCheckinStartOffsetMinute': 1260,
            'studentCheckinEndOffsetMinute': 1410}


def record(status='PENDING'):
    return {'businessDate': DAY, 'recordStatusCode': status, 'abnormalFlag': False,
            'checkinTime': DAY+' 22:00:00' if status == 'CHECKED_IN' else None}


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.attempts = Attempts(Path(self.temp.name))
        self.school = MagicMock()
        self.school.enter.return_value = record()
        self.school.today.return_value = record()
        self.school.schedule.return_value = SCHEDULE
        self.school.locations.return_value = [{**normalize_location(POINT)['gcj02'], 'radiusMeter': 150}]
        self.school.reverse_geocode.return_value = '合成测试地址'
        self.school_patch = patch('checkin.school_for', return_value=self.school)
        self.school_patch.start()
        self.clock_patch = patch('checkin.now', return_value=INSTANT)
        self.clock_patch.start()

    def tearDown(self):
        self.clock_patch.stop()
        self.school_patch.stop()
        self.temp.cleanup()

    def test_prepare_reads_only_and_returns_address(self):
        preview = prepare_checkin(SNAPSHOT, POINT)
        self.assertEqual(preview['address'], '合成测试地址')
        self.assertFalse(preview['submitted'])
        self.school.submit.assert_not_called()

    def test_confirmed_only_after_readback(self):
        self.school.today.side_effect = [record(), record(), record('CHECKED_IN')]
        result = submit_checkin(SNAPSHOT, POINT, self.attempts, sleep=lambda _: None)
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['result'], 'confirmed')
        self.school.submit.assert_called_once()
        payload = self.school.submit.call_args.args[0]
        self.assertEqual(payload['reverseGeocode'], '合成测试地址')
        self.assertEqual(payload['coordinateSystemCode'], 'gcj02')

    def test_timeout_never_causes_second_post_even_after_restart(self):
        self.school.submit.side_effect = ToolError('timeout', 'checkin_post')
        result = submit_checkin(SNAPSHOT, POINT, self.attempts, sleep=lambda _: None)
        self.assertEqual(result['result'], 'unknown')
        restored = Attempts(Path(self.temp.name))
        second = submit_checkin(SNAPSHOT, POINT, restored, sleep=lambda _: None)
        self.assertEqual(second['result'], 'prior_attempt')
        self.assertFalse(second['submitted'])
        self.school.submit.assert_called_once()

    def test_confirmation_address_reused_without_duplicate_schedule_query(self):
        self.school.today.side_effect = [record(), record(), record('CHECKED_IN')]
        result = submit_checkin(SNAPSHOT, POINT, self.attempts, address='已确认地址', sleep=lambda _: None)
        self.assertTrue(result['confirmed'])
        self.school.reverse_geocode.assert_not_called()
        self.school.schedule.assert_called_once()
        self.assertEqual(self.school.submit.call_args.args[0]['reverseGeocode'], '已确认地址')

    def test_existing_school_record_skips_post(self):
        self.school.today.return_value = record('CHECKED_IN')
        result = submit_checkin(SNAPSHOT, POINT, self.attempts)
        self.assertEqual(result['result'], 'already_recorded')
        self.assertFalse(result['submitted'])
        self.school.submit.assert_not_called()

    def test_outside_window_and_fence_prevent_post(self):
        self.school.schedule.return_value = {**SCHEDULE, 'studentCheckinStartOffsetMinute': 0,
                                            'studentCheckinEndOffsetMinute': 30}
        with self.assertRaises(ToolError) as error:
            submit_checkin(SNAPSHOT, POINT, self.attempts)
        self.assertEqual(error.exception.reason, 'outside_checkin_window')
        self.school.schedule.return_value = SCHEDULE
        self.school.locations.return_value = [{'latitude': 0, 'longitude': 0, 'radiusMeter': 50}]
        with self.assertRaises(ToolError) as error:
            submit_checkin(SNAPSHOT, POINT, self.attempts)
        self.assertEqual(error.exception.reason, 'outside_allowed_location')
        self.school.submit.assert_not_called()

    def test_persistent_claim_is_exclusive(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed = list(pool.map(lambda _: self.attempts.claim('synthetic-hash', DAY), range(4)))
        self.assertEqual(sum(claimed), 1)


class TransportTests(unittest.TestCase):
    def test_post_is_exact_one_shot_capability(self):
        transport = SubmissionTransport(SNAPSHOT)
        with patch('core.Transport.request') as network:
            with self.assertRaises(ToolError):
                transport.request('POST', SUBMIT_URL, stage='checkin_post', payload={})
            transport.permit = True
            transport.request('POST', SUBMIT_URL, stage='checkin_post', payload={})
            with self.assertRaises(ToolError):
                transport.request('POST', SUBMIT_URL, stage='checkin_post', payload={})
            network.assert_called_once()

    def test_capability_does_not_allow_report(self):
        transport = SubmissionTransport(SNAPSHOT)
        transport.permit = True
        with patch('core.Transport.request') as network:
            with self.assertRaises(ToolError):
                transport.request('POST', SUBMIT_URL.replace('/checkin', '/report'), stage='checkin_post', payload={})
            network.assert_not_called()


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.clock_patch = patch('app.now', return_value=INSTANT)
        self.clock_patch.start()
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name)
        self.client = self.app.test_client()
        self.store = self.app.extensions['local_store']
        self.store.save_session(SNAPSHOT)
        self.store.save_location(POINT)
        csrf = self.client.get('/api/status', base_url=BASE).json['csrf']
        self.headers = {'Origin': BASE, 'X-CSRF-Token': csrf}

    def tearDown(self):
        self.clock_patch.stop()
        self.temp.cleanup()

    def post(self, url, data):
        return self.client.post(url, json=data, base_url=BASE, headers=self.headers)

    def ticket(self):
        with patch('app.prepare_checkin', return_value={'businessDate': DAY, 'submitted': False}):
            response = self.post('/api/checkin/prepare', {})
        self.assertEqual(response.status_code, 200)
        return response.json['confirmation']

    def test_confirmation_consumed_once_and_requires_both_checks(self):
        token = self.ticket()
        data = {'confirmation': token, 'confirm': True, 'actual_location_confirmed': True}
        with patch('app.submit_checkin', return_value={'confirmed': True, 'submitted': True}) as submit:
            self.assertEqual(self.post('/api/checkin', {**data, 'confirm': False}).status_code, 400)
            self.assertEqual(self.post('/api/checkin', {**data, 'actual_location_confirmed': False}).status_code, 400)
            self.assertEqual(self.post('/api/checkin', data).status_code, 200)
            self.assertEqual(self.post('/api/checkin', data).status_code, 400)
            submit.assert_called_once()

    def test_changed_location_invalidates_confirmation(self):
        token = self.ticket()
        self.store.save_location({**POINT, 'latitude': 30.8})
        with patch('app.submit_checkin') as submit:
            response = self.post('/api/checkin', {'confirmation': token, 'confirm': True, 'actual_location_confirmed': True})
            self.assertEqual(response.status_code, 400)
            submit.assert_not_called()

    def test_expired_confirmation_never_submits(self):
        token = self.ticket()
        with patch('app.time.monotonic', return_value=10**18), patch('app.submit_checkin') as submit:
            response = self.post('/api/checkin', {'confirmation': token, 'confirm': True, 'actual_location_confirmed': True})
            self.assertEqual(response.status_code, 400)
            submit.assert_not_called()
