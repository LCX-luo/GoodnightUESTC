"""Synthetic storage records only. No ADB or school network traffic."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core import ToolError
from mumu_session import (CaptureError, MuMuReader, crc32c, current_entries,
                          school_tickets, run_action, summary)


def varint(value):
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def field(value):
    return varint(len(value)) + value


def log(updates, sequence=1):
    batch = struct.pack('<QI', sequence, len(updates))
    for key, value in updates:
        batch += bytes([0 if value is None else 1]) + field(key)
        if value is not None:
            batch += field(value)
    crc = crc32c(b'\1' + batch)
    checksum = (((crc >> 15) | (crc << 17)) + 0xa282ead8) & 0xffffffff
    return struct.pack('<IHB', checksum, len(batch), 1) + batch


NAMESPACE = b'namespace-00000000-0000-0000-0000-000000000000-https://jzsz.uestc.edu.cn'
TICKET_KEY = b'map-3-daily-checkin-operation-ticket'


class StorageReaderTests(unittest.TestCase):
    def test_crc32c_known_vector(self):
        self.assertEqual(crc32c(b'123456789'), 0xe3069283)

    def test_requires_matching_school_namespace(self):
        data = log([(NAMESPACE, b'3'), (TICKET_KEY, 'synthetic-ticket'.encode('utf-16-le'))])
        self.assertEqual(school_tickets([data]), {'synthetic-ticket'})
        other = log([(NAMESPACE.replace(b'jzsz.uestc.edu.cn', b'other.example'), b'3'),
                     (TICKET_KEY, 'unrelated'.encode('utf-16-le'))])
        self.assertEqual(school_tickets([other]), set())

    def test_deleted_namespace_cannot_resurrect_old_ticket(self):
        first = log([(NAMESPACE, b'3'), (TICKET_KEY, 'old'.encode('utf-16-le'))])
        deletion = log([(NAMESPACE, None)], sequence=3)
        self.assertEqual(school_tickets([first, deletion]), set())

    def test_deleted_ticket_cannot_resurrect(self):
        first = log([(NAMESPACE, b'3'), (TICKET_KEY, 'old'.encode('utf-16-le'))])
        deletion = log([(TICKET_KEY, None)], sequence=3)
        self.assertEqual(school_tickets([deletion, first]), set())

    def test_sequence_wins_over_filename_order(self):
        first = log([(NAMESPACE, b'3'), (TICKET_KEY, 'old'.encode('utf-16-le'))])
        last = log([(TICKET_KEY, 'new'.encode('utf-16-le'))], sequence=3)
        self.assertEqual(school_tickets([last, first]), {'new'})

    def test_checksum_corruption_and_truncation_are_rejected(self):
        data = log([(NAMESPACE, b'3')])
        for broken in (data[:-1], data[:-1] + bytes([data[-1] ^ 1])):
            with self.assertRaises(CaptureError):
                current_entries([broken])

    def test_header_injection_rejected(self):
        data = log([(NAMESPACE, b'3'), (TICKET_KEY, 'bad\r\nheader'.encode('utf-16-le'))])
        with self.assertRaises(CaptureError):
            school_tickets([data])

    def test_compacted_tables_are_not_treated_as_current_log_only_state(self):
        reader = object.__new__(MuMuReader)
        reader.run = MagicMock(return_value=b'000003.log\n000005.ldb\n')
        with self.assertRaises(CaptureError):
            reader.tickets('/synthetic')

    def test_cannot_implicitly_target_physical_phone(self):
        with self.assertRaises(CaptureError):
            MuMuReader('/unused', 'synthetic-phone-serial')

    def test_summary_never_contains_credentials(self):
        snapshot = {'operation_ticket': 'synthetic-secret-ticket', 'cookies': [
            {'domain': 'jzsz.uestc.edu.cn', 'name': 'SESSION', 'path': '/', 'value': 'synthetic-secret-cookie'}]}
        report = str(summary(snapshot))
        self.assertNotIn(snapshot['operation_ticket'], report)
        self.assertNotIn(snapshot['cookies'][0]['value'], report)


class Actions(unittest.TestCase):
    def environment(self, directory, stack):
        stack.enter_context(patch('builtins.print'))
        store = MagicMock()
        store.directory = Path(directory)
        store.session.return_value = {'student_id': 'synthetic-account', 'user_agent': 'synthetic-agent'}
        stack.enter_context(patch('core.LocalStore', return_value=store))
        reader = stack.enter_context(patch('mumu_session.MuMuReader')).return_value
        reader.capture.return_value = {'operation_ticket': 'synthetic-ticket', 'cookies': [], 'user_agent': 'synthetic-agent'}
        stack.enter_context(patch('core.ReadOnlyTransport'))
        school = stack.enter_context(patch('core.ReadOnlySchool')).return_value
        school.today.return_value = {'studentSn': 'synthetic-account', 'recordStatusCode': 'PENDING'}
        prepare = stack.enter_context(patch('checkin.prepare_checkin'))
        submit = stack.enter_context(patch('checkin.submit_checkin'))
        stack.enter_context(patch('checkin.Attempts'))
        return store, school, prepare, submit

    def test_inspect_neither_saves_nor_submits(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            store, school, prepare, submit = self.environment(directory, stack)
            run_action('inspect', '127.0.0.1:16384')
            store.save_session.assert_not_called()
            prepare.assert_not_called()
            submit.assert_not_called()

    def test_other_account_is_not_imported(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            store, school, prepare, submit = self.environment(directory, stack)
            school.today.return_value = {'studentSn': 'different-synthetic-account'}
            with self.assertRaises(CaptureError):
                run_action('import', '127.0.0.1:16384')
            store.save_session.assert_not_called()
            submit.assert_not_called()

    def test_import_uses_encrypted_store_and_keeps_old_encrypted_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            store, school, prepare, submit = self.environment(directory, stack)
            old = b'synthetic-encrypted-data'
            (Path(directory) / 'session.enc').write_bytes(old)
            run_action('import', '127.0.0.1:16384')
            self.assertEqual((Path(directory) / 'session-before-mumu.enc').read_bytes(), old)
            self.assertEqual(store.save_session.call_args.args[0]['operation_ticket'], 'synthetic-ticket')
            submit.assert_not_called()

    def test_already_checked_in_never_reaches_submit(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            store, school, prepare, submit = self.environment(directory, stack)
            prepare.side_effect = ToolError('already_recorded')
            with self.assertRaises(ToolError):
                run_action('submit', '127.0.0.1:16384')
            submit.assert_not_called()

    def test_cancel_does_not_submit(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            store, school, prepare, submit = self.environment(directory, stack)
            prepare.return_value = {'businessDate': 'synthetic-date', 'address': 'synthetic-address'}
            stack.enter_context(patch('builtins.input', return_value='cancel'))
            with self.assertRaises(CaptureError):
                run_action('submit', '127.0.0.1:16384')
            submit.assert_not_called()

    def test_explicit_confirmation_reaches_existing_one_shot_submission_once(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            store, school, prepare, submit = self.environment(directory, stack)
            day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
            prepare.return_value = {'businessDate': day, 'address': 'synthetic-address'}
            stack.enter_context(patch('builtins.input', return_value='确认提交'))
            run_action('submit', '127.0.0.1:16384')
            submit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
