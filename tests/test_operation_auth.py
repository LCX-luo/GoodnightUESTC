"""Official authorization tickets are opaque secrets; all transports are mocked."""
import unittest
from unittest.mock import MagicMock
from core import ToolError
from checkin import school_for
from moonuestc.client import School
from moonuestc.operation_auth import operation_headers
from moonuestc.diagnostics import school_message


class OperationAuthorization(unittest.TestCase):
    def school(self, ticket=None, code=0):
        transport = MagicMock()
        response = transport.request.return_value
        response.status = 200
        response.json.return_value = {'code': code, 'data': {}, 'msg': '请从微信小程序重新进入打卡应用后提交'}
        return School(transport, {'operation_ticket': ticket}, lambda: None)

    def test_missing_ticket_never_calls_transport(self):
        school = self.school()
        with self.assertRaises(ToolError) as raised:
            school.submit({})
        self.assertEqual(raised.exception.reason, 'operation_ticket_required')
        school.transport.request.assert_not_called()

    def test_only_submission_carries_ticket(self):
        school = self.school('synthetic-ticket-value')
        school.submit({})
        self.assertEqual(school.transport.request.call_args.kwargs['headers']['X-Checkin-Ticket'], 'synthetic-ticket-value')
        school.today()
        self.assertNotIn('X-Checkin-Ticket', school.transport.request.call_args.kwargs['headers'])

    def test_server_rejection_preserves_code_without_retry(self):
        school = self.school('synthetic-ticket-value', 46001)
        with self.assertRaises(ToolError) as raised:
            school.submit({})
        self.assertEqual(raised.exception.reason, 'operation_ticket_rejected')
        self.assertEqual(raised.exception.api_code, 46001)
        self.assertEqual(school.transport.request.call_count, 1)

    def test_invalid_header_is_rejected(self):
        for value in ('ticket\r\nInjected: yes', 'has space', '非ASCII', {}, 'a'*8193):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ToolError):
                operation_headers(value)

    def test_consumed_ticket_is_unknown_and_never_retried(self):
        school = self.school('synthetic-ticket-value', 46004)
        with self.assertRaises(ToolError) as raised:
            school.submit({})
        self.assertEqual(raised.exception.reason, 'operation_ticket_pending')
        self.assertEqual(raised.exception.api_code, 46004)
        school.transport.request.assert_called_once()

    def test_missing_authorization_fails_before_creating_writable_transport(self):
        with self.assertRaises(ToolError) as raised:
            school_for({'student_id': 'synthetic'}, writable=True)
        self.assertEqual(raised.exception.reason, 'operation_ticket_required')

    def test_ticket_is_removed_from_echoed_diagnostics(self):
        ticket = 'synthetic-opaque-secret'
        result = school_message('echo '+ticket, {'operation_ticket': ticket})
        self.assertNotIn(ticket, result)


if __name__ == '__main__':
    unittest.main()
