"""Read only the owner's school-origin WebView session on a rooted MuMu.

No UI control, system modifications, or attendance submission. The current
implementation deliberately refuses compacted LevelDB tables rather than
mistaking a historical log entry for a current authorization ticket.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import struct
import subprocess
import tempfile
import argparse
from datetime import datetime, timedelta, timezone
import sys
import time

ORIGIN = 'https://jzsz.uestc.edu.cn'
KEY = b'daily-checkin-operation-ticket'


class CaptureError(Exception):
    pass


def crc32c(data):
    value = 0xffffffff
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0x82f63b78 if value & 1 else 0)
    return value ^ 0xffffffff


def varint(data, pos):
    result = 0
    for shift in range(0, 64, 7):
        if pos >= len(data):
            raise CaptureError('会话日志不完整，请等待页面加载后重试读取。')
        byte = data[pos]
        pos += 1
        result |= (byte & 127) << shift
        if byte < 128:
            return result, pos
    raise CaptureError('无效日志长度。')


def blob(data, pos):
    length, pos = varint(data, pos)
    if pos + length > len(data):
        raise CaptureError('会话日志不完整。')
    return data[pos:pos + length], pos + length


def wal_records(data):
    pending = None
    for start in range(0, len(data), 32768):
        block = data[start:start + 32768]
        pos = 0
        while pos + 7 <= len(block):
            checksum, length, kind = struct.unpack_from('<IHB', block, pos)
            pos += 7
            if checksum == length == kind == 0 and not any(block[pos:]):
                break
            if pos + length > len(block):
                raise CaptureError('日志写入尚未完成。')
            body = block[pos:pos + length]
            pos += length
            crc = crc32c(bytes([kind]) + body)
            masked = (((crc >> 15) | (crc << 17)) + 0xa282ead8) & 0xffffffff
            if checksum != masked:
                raise CaptureError('日志校验失败，请重新读取。')
            if kind == 1 and pending is None:
                yield body
            elif kind == 2 and pending is None:
                pending = bytearray(body)
            elif kind in (3, 4) and pending is not None:
                pending.extend(body)
                if kind == 4:
                    yield bytes(pending)
                    pending = None
            else:
                raise CaptureError('不支持的日志片段。')
        if any(block[pos:]):
            raise CaptureError('日志尾部不完整。')
    if pending is not None:
        raise CaptureError('日志记录不完整。')


def current_entries(logs):
    updates = {}
    for data in logs:
        for batch in wal_records(data):
            if len(batch) < 12:
                raise CaptureError('无效写入批次。')
            sequence, count = struct.unpack_from('<QI', batch)
            pos = 12
            for index in range(count):
                if pos >= len(batch):
                    raise CaptureError('写入批次不完整。')
                kind = batch[pos]
                pos += 1
                key, pos = blob(batch, pos)
                if kind == 1:
                    value, pos = blob(batch, pos)
                elif kind == 0:
                    value = None
                else:
                    raise CaptureError('不支持的写入类型。')
                seq = sequence + index
                if key not in updates or seq > updates[key][0]:
                    updates[key] = (seq, value)
            if pos != len(batch):
                raise CaptureError('批次长度不匹配。')
    return {key: value for key, (_, value) in updates.items() if value is not None}


def school_tickets(logs):
    entries = current_entries(logs)
    maps = set()
    for key, value in entries.items():
        if key.startswith(b'namespace-') and (key.endswith(('-' + ORIGIN).encode())
                                              or key.endswith(('-' + ORIGIN + '/').encode())):
            if not re.fullmatch(rb'\d+', value):
                raise CaptureError('不支持的会话命名空间。')
            maps.add(value)
    tickets = set()
    for map_id in maps:
        value = entries.get(b'map-' + map_id + b'-' + KEY)
        if value is None:
            continue
        try:
            ticket = value.decode('utf-16-le')
        except UnicodeError:
            raise CaptureError('不支持的票据编码。') from None
        if not re.fullmatch(r'[!-~]{1,8192}', ticket):
            raise CaptureError('无效的操作票据格式。')
        tickets.add(ticket)
    return tickets


def adb_path():
    for path in (os.environ.get('ADB'), shutil.which('adb'),
                 str(Path(os.environ.get('LOCALAPPDATA', '')) / 'Android/Sdk/platform-tools/adb.exe'),
                 r'C:\Program Files\Netease\MuMu\nx_main\adb.exe'):
        if path and Path(path).is_file():
            return path
    raise CaptureError('找不到 adb.exe。')


class MuMuReader:
    def __init__(self, directory, serial='127.0.0.1:16384'):
        if not re.fullmatch(r'127\.0\.0\.1:\d{2,5}', serial):
            raise CaptureError('仅支持本机 MuMu 端口，不连接真实手机。')
        self.adb, self.serial = adb_path(), serial
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.run('shell', 'id', '-u').strip() != b'0':
            raise CaptureError('MuMu ADB 尚未开启 Root。')

    def run(self, *args):
        result = subprocess.run([self.adb, '-s', self.serial, *args], capture_output=True, timeout=20)
        if result.returncode:
            raise CaptureError('MuMu 数据读取失败。')
        return result.stdout

    def read(self, path):
        # Paths are generated locally, never supplied by a page or remote response.
        return self.run('exec-out', 'cat ' + shlex.quote(path))

    def tickets(self, profile):
        directory = profile + '/Session Storage'
        names = self.run('shell', 'ls -1 ' + shlex.quote(directory)).decode('utf-8').splitlines()
        if any(name.endswith(('.ldb', '.sst')) for name in names):
            raise CaptureError('会话存储已压缩为数据表，当前读取器不能可靠还原。')
        logs = [self.read(directory + '/' + name) for name in names if re.fullmatch(r'\d+\.log', name)]
        return school_tickets(logs)

    def cookies(self, profile):
        data = self.read(profile + '/Cookies')
        if not data.startswith(b'SQLite format 3\0'):
            raise CaptureError('Cookie 数据库格式不支持。')
        fd, filename = tempfile.mkstemp(dir=self.directory, suffix='.sqlite')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
            db = sqlite3.connect(filename)
            try:
                rows = db.execute("SELECT host_key,name,value,encrypted_value,path,expires_utc,"
                                  "is_secure,is_httponly,has_expires FROM cookies WHERE "
                                  "host_key IN ('jzsz.uestc.edu.cn','.jzsz.uestc.edu.cn')").fetchall()
            finally:
                db.close()
        finally:
            os.unlink(filename)
        result = []
        for host, name, value, encrypted, path, expires, secure, http_only, has_expires in rows:
            if not value and encrypted:
                raise CaptureError('学校 Cookie 已加密，不能直接读取。')
            if not value:
                continue
            if any(char in name + value for char in '\r\n'):
                raise CaptureError('Cookie 格式异常。')
            result.append({'domain': host, 'name': name, 'value': value, 'path': path,
                           'expires': expires / 1000000 - 11644473600 if has_expires else -1,
                           'secure': bool(secure), 'httpOnly': bool(http_only)})
        if not any(cookie['name'] == 'SESSION' for cookie in result):
            raise CaptureError('此 WebView 中没有学校 SESSION。')
        return result

    def capture(self, user_agent):
        profile = '/data/user/0/com.tencent.mm/app_webview_com_tencent_mm_appbrand0/Default'
        tickets = self.tickets(profile)
        if len(tickets) != 1:
            raise CaptureError('未找到唯一的学校操作票据，请从小程序首页重新进入。')
        cookies = self.cookies(profile)
        if self.tickets(profile) != tickets:
            raise CaptureError('读取期间票据发生变化，请重新采集。')
        ticket = next(iter(tickets))
        return {'operation_ticket': ticket, 'cookies': cookies, 'user_agent': user_agent,
                'source': 'mumu-school-webview', 'student_id': ''}


def summary(snapshot):
    ticket = snapshot['operation_ticket']
    cookie_data = sorted((c['domain'], c['name'], c['path'], c['value']) for c in snapshot['cookies'])
    return {'ticket_present': True, 'ticket_length': len(ticket),
            'ticket_sha256': hashlib.sha256(ticket.encode()).hexdigest(),
            'cookie_count': len(cookie_data),
            'cookies_sha256': hashlib.sha256(json.dumps(cookie_data).encode()).hexdigest()}


def run_action(action, serial):
    # Imported lazily so the offline parser is independent of application deps.
    from core import LocalStore, ReadOnlySchool, ReadOnlyTransport
    from checkin import prepare_checkin, submit_checkin, Attempts
    root = Path(__file__).resolve().parent
    store = LocalStore(root / 'private-data')
    previous = store.session()
    if not previous or not previous.get('user_agent'):
        raise CaptureError('请先用本机工具登录一次，建立桌面请求配置。')
    snapshot = MuMuReader(store.directory / 'ticket-research', serial).capture(previous['user_agent'])
    school = ReadOnlySchool(ReadOnlyTransport(snapshot), {'student_id': ''}, lambda: None)
    record = school.today()
    student_id = str(record.get('studentSn') or '')
    if not student_id:
        raise CaptureError('学校没有返回可核对的账号信息。')
    if student_id != str(previous.get('student_id') or ''):
        raise CaptureError('MuMu 与桌面保存的账号不同，请先确认当前登录账号。')
    snapshot.update(student_id=student_id, saved_at=time.time(),
                    user_agent_source='desktop_profile_not_observed_wechat_ua')
    result = summary(snapshot)
    result.update(source='mumu-school-webview', record_status=record.get('recordStatusCode'),
                  business_date=record.get('businessDate'), submitted=False,
                  ticket_validated_for_new_checkin=False)
    if action == 'inspect':
        return result
    if action == 'import':
        # Keep the prior encrypted snapshot with the same vault key and purpose.
        path = store.directory / 'session.enc'
        backup = store.directory / 'session-before-mumu.enc'
        if path.exists() and not backup.exists():
            with backup.open('xb') as stream:
                stream.write(path.read_bytes())
        store.save_session(snapshot)
        return dict(result, imported=True, message='已验证登录会话并导入；票据是否可创建新签到尚待验证。')
    location = store.location()
    prepared = prepare_checkin(snapshot, location)
    if action == 'prepare':
        return dict(result, prepared=prepared)
    print('已完成只读预检查。请核对电脑地图中保存的位置及本人实际位置。', flush=True)
    print(json.dumps(prepared, ensure_ascii=False, indent=2), flush=True)
    expected = prepared['businessDate']
    confirmation_started = time.monotonic()
    if input('向学校正式提交一次，请输入“确认提交”：').strip() != '确认提交':
        raise CaptureError('已取消，未提交。')
    if time.monotonic() - confirmation_started > 120:
        raise CaptureError('确认超过两分钟，请重新读取会话并预检查。')
    instant = datetime.now(timezone(timedelta(hours=8)))
    if instant.date().isoformat() != expected:
        raise CaptureError('日期已变化，请重新预检查。')
    # The existing submission function rechecks session/day/window/fence and
    # durably claims one POST per account/day before making the request.
    return submit_checkin(snapshot, location, Attempts(store.directory), address=prepared['address'])


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='读取 MuMu 中本人学校操作授权，用于电脑 HTTP 脚本。不会操作界面。')
    parser.add_argument('action', nargs='?', default='inspect',
                        choices=['inspect', 'import', 'prepare', 'submit'])
    parser.add_argument('--serial', default='127.0.0.1:16384')
    args = parser.parse_args()
    try:
        print(json.dumps(run_action(args.action, args.serial), ensure_ascii=False, indent=2))
        return 0
    except CaptureError as error:
        message = str(error)
    except KeyboardInterrupt:
        message = '已中断；若已进入提交阶段，请先在官方页面核对结果。'
    except Exception as error:
        # Do not echo URLs, cookies, raw response bodies, or subprocess output.
        reason = getattr(error, 'reason', None)
        if reason == 'already_recorded':
            message = '学校记录显示今天已处理，未发送签到请求。'
        elif reason:
            message = '操作未完成：' + str(reason)
        else:
            message = '操作未完成（' + type(error).__name__ + '），未自动重试。'
    print(json.dumps({'state': 'stopped', 'message': message}, ensure_ascii=False))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
