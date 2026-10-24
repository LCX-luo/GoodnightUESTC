"""Accept only an opaque ticket issued by the official application; never mint one."""
import re
from .errors import ToolError


def operation_headers(ticket):
    if not ticket:
        raise ToolError('operation_ticket_required', 'operation_authorization')
    if not isinstance(ticket, str) or not re.fullmatch(r'[!-~]{1,8192}', ticket):
        raise ToolError('operation_ticket_invalid', 'operation_authorization')
    return {'X-Checkin-Ticket': ticket}
