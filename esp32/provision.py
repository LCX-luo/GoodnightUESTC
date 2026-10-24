"""USB-only local provisioning. Never writes exported credentials to a file."""
import argparse
import base64
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def configuration(enable=False, only=None):
    from core import LocalStore, normalize_location
    from wechat_auth import WeChatAuthorization, school_session
    directory = ROOT / 'private-data/profiles'
    index = json.loads((directory / 'index.json').read_text('utf-8'))
    accounts = []
    for profile in index:
        if profile.get('saved') is False:
            continue
        store = LocalStore(directory / profile['id'])
        snapshot, point = store.session(), store.location()
        if not snapshot or not point:
            continue
        if only and snapshot['student_id'] != only:
            continue
        credentials = WeChatAuthorization(store).cached(snapshot)
        if not credentials:
            continue
        point = normalize_location(point)['gcj02']
        accounts.append({'student_id': snapshot['student_id'], 'schoolSession': school_session(snapshot),
                         'wechat': credentials, 'location': {**point, 'coordinate_system': 'gcj02'}})
    if not 1 <= len(accounts) <= 4:
        raise RuntimeError('Expected one to four complete saved profiles; check the account library.')
    return {'version': 1, 'enabled': enable, 'accounts': accounts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM4')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('operation', choices=['status', 'import', 'probe'])
    parser.add_argument('--account')
    parser.add_argument('--enable-schedule', action='store_true')
    parser.add_argument('--submit-once', action='store_true', help='Real attendance write, only with probe')
    args = parser.parse_args()
    if args.submit_once and args.operation != 'probe':
        parser.error('--submit-once requires probe')
    message = {'op': args.operation}
    if args.operation == 'import':
        message['config'] = configuration(args.enable_schedule, args.account)
    if args.operation == 'probe':
        if not args.account:
            parser.error('probe requires --account')
        message.update(account=args.account, submit=args.submit_once)
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
                    'checkin_confirmed', 'existing_record_only', 'result_unknown_no_retry'}
        while time.monotonic() < deadline:
            line = port.readline()
            if not line.startswith(b'GN1 {'):
                continue  # Never echo firmware boot logs or serial input containing credentials.
            try:
                value = json.loads(line[4:])
            except ValueError:
                continue
            allowed = {key: value[key] for key in ('state', 'account', 'code', 'heap', 'largestBlock') if key in value}
            print(json.dumps(allowed), flush=True)
            state = value.get('state', '')
            failure = state.endswith(('_failed', '_unavailable', '_mismatch', '_unsynchronized', '_missing', '_invalid', '_rejected')) and state != 'request_rejected'
            if state in terminal or failure or state in {'school_business', 'out_of_memory', 'runtime_error', 'account_not_found', 'prior_attempt_today', 'outside_checkin_window', 'outside_allowed_location', 'insufficient_heap'}:
                return
        raise RuntimeError('Device response timed out; do not automatically repeat a submission.')
    finally:
        port.close()


if __name__ == '__main__':
    main()
