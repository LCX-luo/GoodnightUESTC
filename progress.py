"""Small, secret-free progress snapshot for synchronous school operations."""
from contextlib import contextmanager
import threading
import time


class Progress:
    def __init__(self):
        self.lock = threading.Lock()
        self.value = None

    @contextmanager
    def operation(self, kind):
        with self.lock:
            self.value = {'kind': kind, 'active': True, 'message': '正在连接学校…', 'started': time.monotonic()}
        try:
            yield
        finally:
            with self.lock:
                if self.value:
                    self.value['elapsed'] = round(time.monotonic()-self.value['started'], 1)
                    self.value['active'] = False

    def step(self, message):
        with self.lock:
            if self.value and self.value['active']:
                self.value['message'] = message

    def snapshot(self):
        with self.lock:
            if not self.value:
                return None
            value = {k: v for k, v in self.value.items() if k != 'started'}
            if value['active']:
                value['elapsed'] = round(time.monotonic()-self.value['started'], 1)
            return value
