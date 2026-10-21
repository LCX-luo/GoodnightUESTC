"""Packaged runtime test: synthetic encryption + diagnostics + blank Edge only."""
import tempfile
from core import LocalStore, offline_test


def run():
    with tempfile.TemporaryDirectory() as directory:
        store = LocalStore(directory)
        sample = {'cookies': [], 'user_agent': 'Synthetic Runtime Test', 'student_id': '000000000000'}
        store.save_session(sample)
        assert store.session() == sample
        assert offline_test(None)['schoolRequests'] == 0
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        try:
            assert browser.new_page().evaluate('1 + 1') == 2
        finally:
            browser.close()
    print('Runtime self-test PASS: encryption, offline guards, Edge; schoolRequests=0')
