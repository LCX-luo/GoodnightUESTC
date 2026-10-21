"""Explicit one-shot attendance, with durable per-account/day claims and readback."""
import hashlib
from contextlib import contextmanager
import sqlite3
import time
from core import (ReadOnlyTransport, ReadOnlySchool, Transport, School, ToolError,
                  ORIGIN, normalize_location, now, valid_today, window, check_fence, read_today)
from moonuestc.policy import build_payload, verified, TERMINAL

SUBMIT_URL = ORIGIN + '/daily-checkin/api/student-checkin-record/checkin'


class Attempts:
    def __init__(self, directory):
        self.path = directory / 'attempts.sqlite3'
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS attempts (account TEXT, day TEXT, outcome TEXT, '
                       'created REAL NOT NULL, PRIMARY KEY(account,day))')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def claim(self, account, day):
        with self.db() as db:
            db.execute('PRAGMA synchronous=FULL')
            cursor = db.execute('INSERT OR IGNORE INTO attempts VALUES (?,?,?,?)',
                                (account, day, 'started', time.time()))
            return cursor.rowcount == 1

    def finish(self, account, day, outcome):
        with self.db() as db:
            db.execute('UPDATE attempts SET outcome=? WHERE account=? AND day=?', (outcome, account, day))

    def exists(self, account, day):
        with self.db() as db:
            return db.execute('SELECT 1 FROM attempts WHERE account=? AND day=?', (account, day)).fetchone() is not None


class SubmissionTransport(ReadOnlyTransport):
    def __init__(self, snapshot):
        super().__init__(snapshot)
        self.permit = False

    def request(self, method, url, *, stage, headers=None, form=None, payload=None):
        if self.permit and method == 'POST' and url == SUBMIT_URL and stage == 'checkin_post' and isinstance(payload, dict) and form is None:
            self.permit = False  # One POST per transport, even if the response fails.
            return Transport.request(self, method, url, stage=stage, headers=headers, payload=payload)
        return super().request(method, url, stage=stage, headers=headers, form=form, payload=payload)


def school_for(snapshot, writable=False):
    transport = SubmissionTransport(snapshot) if writable else ReadOnlyTransport(snapshot)
    cls = School if writable else ReadOnlySchool
    return cls(transport, {'student_id': snapshot['student_id']}, lambda: None, emit=lambda *a, **k: None)


def configured_payload(snapshot, location):
    location = normalize_location(location)
    return build_payload({'user_agent': snapshot['user_agent'], 'location': {
        'mode': 'fixed', 'name': location['name'], 'latitude': location['latitude'],
        'longitude': location['longitude'], 'coordinate_system': location['coordinate_system'],
        'request_metadata': {'accuracy': 0, 'locationDurationMs': 0, 'networkTypeCode': 'unknown',
                             'locationEnabled': False, 'locationAuthorized': '', 'locationAccuracy': '',
                             'errorMessage': ''}}}, now())


def prepare_checkin(snapshot, location, *, progress=lambda message: None):
    if not location:
        raise ToolError('location_required')
    school = school_for(snapshot)
    progress('正在读取学校当天记录…')
    record = read_today(school)
    instant = now()
    status = valid_today(record, instant)
    if status in TERMINAL:
        raise ToolError('already_recorded')
    payload = configured_payload(snapshot, location)
    progress('正在检查所选位置的允许范围…')
    check_fence(payload, school.locations())
    progress('正在检查学校允许的签到时段…')
    schedule = window(school.schedule(), now())
    if not schedule['open']:
        raise ToolError('outside_checkin_window')
    progress('正在查询所选位置的地址…')
    address = school.reverse_geocode(payload['latitude'], payload['longitude'])
    return {'businessDate': instant.date().isoformat(), 'name': location['name'],
            'latitude': payload['latitude'], 'longitude': payload['longitude'],
            'address': address, 'window': schedule, 'submitted': False}


def submit_checkin(snapshot, location, attempts, *, sleep=time.sleep, address=None, progress=lambda message: None):
    """Caller must validate explicit, session-bound, short-lived confirmation first."""
    school = school_for(snapshot, writable=True)
    day = now().date().isoformat()
    key = hashlib.sha256(snapshot['student_id'].encode()).hexdigest()
    progress('正在检查学校当天是否已有签到记录…')
    record = read_today(school)
    status = valid_today(record, now())
    if status in TERMINAL:
        return {'mode': 'checkin', 'result': 'already_recorded', 'recordStatus': status,
                'businessDate': day, 'submitted': False, 'confirmed': verified(record, now())}
    if attempts.exists(key, day):
        return {'mode': 'checkin', 'result': 'prior_attempt', 'recordStatus': status,
                'businessDate': day, 'submitted': False, 'confirmed': False}
    payload = configured_payload(snapshot, location)
    progress('正在复核学校允许的位置范围…')
    check_fence(payload, school.locations())
    if not address:
        progress('正在查询签到地址…')
        address = school.reverse_geocode(payload['latitude'], payload['longitude'])
    progress('正在复核学校签到时段…')
    schedule_data = school.schedule()
    if not window(schedule_data, now())['open']:
        raise ToolError('outside_checkin_window')
    progress('正在做提交前的最后记录检查…')
    fresh = school.today()
    if valid_today(fresh, now()) in TERMINAL:
        return {'mode': 'checkin', 'result': 'already_recorded', 'recordStatus': fresh['recordStatusCode'],
                'businessDate': day, 'submitted': False, 'confirmed': verified(fresh, now())}
    if now().date().isoformat() != day:
        raise ToolError('business_date_changed')
    if not window(schedule_data, now())['open']:
        raise ToolError('outside_checkin_window')
    payload = configured_payload(snapshot, location)
    payload['reverseGeocode'] = address
    if not attempts.claim(key, day):
        return {'mode': 'checkin', 'result': 'prior_attempt', 'recordStatus': fresh['recordStatusCode'],
                'businessDate': day, 'submitted': False, 'confirmed': False}
    result = {'mode': 'checkin', 'result': 'unknown', 'businessDate': day,
              'submitted': True, 'confirmed': False, 'recordStatus': 'PENDING'}
    try:
        progress('正在向学校提交签到，请勿重复点击…')
        school.transport.permit = True
        school.submit(payload)
        result['response'] = 'accepted'
    except ToolError as error:
        result.update(response='rejected' if error.reason == 'business_error' else 'unknown', reason=error.reason)
        if error.api_code is not None:
            result['apiCode'] = error.api_code
    except Exception:
        result.update(response='unknown', reason='submission_response_unknown')
    finally:
        school.transport.permit = False
    for index in range(3):
        if index:
            sleep(2)
        try:
            progress('签到请求已发送，正在第 '+str(index+1)+' 次核对学校记录…')
            if now().date().isoformat() != day:
                result['reason'] = 'business_date_changed'
                break
            record = school.today()
            status = valid_today(record, now())
            result['recordStatus'] = status
            if verified(record, now()):
                result.update(result='confirmed', confirmed=True)
                break
            if status in TERMINAL:
                result['result'] = 'record_changed'
                break
        except Exception:
            continue
    if result['result'] == 'unknown' and result.get('response') == 'rejected':
        result['result'] = 'rejected'
    try:
        attempts.finish(key, day, result['result'])
    except sqlite3.Error:
        # Claim was already committed before POST; preserve the result, never resend.
        pass
    return result
