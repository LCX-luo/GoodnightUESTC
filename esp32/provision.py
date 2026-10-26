"""USB-only local provisioning. Never writes exported credentials to a file."""
import argparse
import base64
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def configuration(enable=False, only=None):
    from core import LocalStore, normalize_location, ToolError
    from wechat_auth import school_session
    directory = ROOT / 'private-data/profiles'
    index = json.loads((directory / 'index.json').read_text('utf-8'))
    selected = {}

    def timestamp(value):
        return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else 0.0

    for profile in index:
        if profile.get('saved') is False:
            continue
        try:
            store = LocalStore(directory / profile['id'])
            snapshot, point = store.session(), store.location()
            if not snapshot or not point:
                continue
            student = snapshot['student_id']
            if only and student != only:
                continue
            path = store.directory / 'wechat.enc'
            if not path.exists():
                continue
            # Read verification time and credentials from ONE encrypted record.
            # Preserve the same account binding rule as WeChatAuthorization.cached.
            authorization = store.vault.open(path.read_bytes(), 'wechat-authorization')
            if not authorization or authorization.get('student_id') != student:
                continue
            credentials = authorization.get('credentials')
            if not isinstance(credentials, dict) or not all(
                isinstance(credentials.get(key), str) and 0 < len(credentials[key]) < 2048
                for key in ('openid', 'access_token', 'refresh_token')
            ) or timestamp(credentials.get('expires_at')) <= 0:
                continue
            point = normalize_location(point)['gcj02']
            # Select the complete paired bundle, never merge materials across profiles.
            account = {'student_id': student, 'schoolSession': school_session(snapshot),
                       'wechat': credentials, 'location': {**point, 'coordinate_system': 'gcj02'}}
            rank = (timestamp(authorization.get('last_verified_at')),
                    timestamp(snapshot.get('saved_at')), timestamp(profile.get('updated_at')))
            if student not in selected or rank > selected[student][0]:
                selected[student] = (rank, account)
        except (OSError, ValueError, TypeError, KeyError, ToolError):
            # One incomplete/corrupt saved entry must not replace a valid paired entry.
            continue
    accounts = [account for _, account in selected.values()]
    if not 1 <= len(accounts) <= 4:
        raise RuntimeError('Expected one to four complete unique saved accounts; check the account library.')
    return {'version': 1, 'enabled': enable, 'accounts': accounts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM4')
    parser.add_argument('--timeout', type=int, help='Response deadline in seconds (default: batch 600, otherwise 180)')
    parser.add_argument('operation', choices=['status', 'import', 'probe', 'batch'])
    parser.add_argument('--account')
    parser.add_argument('--enable-schedule', action='store_true')
    parser.add_argument('--submit-once', action='store_true', help='Real attendance write, only with probe or batch')
    args = parser.parse_args()
    if args.submit_once and args.operation not in ('probe', 'batch'):
        parser.error('--submit-once requires probe or batch')
    if args.operation == 'batch' and args.account:
        parser.error('batch applies to all stored accounts; do not supply --account')
    if args.timeout is None:
        args.timeout = 600 if args.operation == 'batch' else 180
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    message = {'op': args.operation}
    if args.operation == 'import':
        message['config'] = configuration(args.enable_schedule, args.account)
    if args.operation == 'probe':
        if not args.account:
            parser.error('probe requires --account')
        message.update(account=args.account, submit=args.submit_once)
    if args.operation == 'batch':
        message['submit'] = args.submit_once
    import serial
    port = serial.Serial()
    port.port, port.baudrate, port.timeout = args.port, 115200, 0.5
    port.dtr = port.rts = False
    port.open()
    try:
        port.reset_input_buffer()
        wire = base64.b64encode(json.dumps(message, separators=(',', ':')).encode())
        frame = b'GN1 ' + wire + b'\n'
        # IDF console fallback reads a small UART FIFO without a driver ring.
        # Pace imports so long credential frames cannot overflow that FIFO.
        for offset in range(0, len(frame), 32):
            port.write(frame[offset:offset+32])
            port.flush()
            time.sleep(0.02)
        deadline = time.monotonic() + args.timeout
        terminal = {'schedule_enabled', 'schedule_disabled', 'profiles_saved', 'authorization_verified',
                    'checkin_confirmed', 'existing_record_only', 'result_unknown_no_retry', 'submission_rejected', 'accepted_pending'}
        while time.monotonic() < deadline:
            line = port.readline()
            if not line.startswith(b'GN1 {'):
                continue  # Never echo firmware boot logs or serial input containing credentials.
            try:
                value = json.loads(line[4:])
            except ValueError:
                continue
            allowed = {key: value[key] for key in ('state', 'account', 'code', 'heap', 'largestBlock', 'epoch', 'stackFree', 'recordStatus') if key in value}
            print(json.dumps(allowed), flush=True)
            state = value.get('state', '')
            if args.operation == 'batch':
                if state == 'batch_completed':
                    return
                continue  # One account's success or failure must not hide later accounts.
            failure = state.endswith(('_failed', '_unavailable', '_mismatch', '_unsynchronized', '_missing', '_invalid', '_rejected')) and state != 'request_rejected'
            if state in terminal or failure or state in {'school_business', 'out_of_memory', 'runtime_error', 'account_not_found', 'prior_attempt_today', 'outside_checkin_window', 'outside_allowed_location', 'insufficient_heap'}:
                return
        raise RuntimeError('Device response timed out; do not automatically repeat a submission.')
    finally:
        port.close()


if __name__ == '__main__':
    main()
