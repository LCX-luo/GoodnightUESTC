"""Inspect public school login controls only; all POSTs are blocked in this test."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from browser_login import LOGIN_URL
from core import browser_allowed

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    try:
        context = browser.new_context(service_workers='block')
        context.route('**/*', lambda route: route.continue_() if route.request.method == 'GET'
                      and browser_allowed('GET', route.request.url) else route.abort())
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until='domcontentloaded', timeout=45000)
        account = page.locator('input#username:visible').first
        password = page.locator('input#password:visible').first
        account.wait_for(timeout=20000)
        password.click(timeout=10000)
        password.evaluate("element => element.removeAttribute('readonly')")
        assert password.is_editable()
        assert page.locator('#login_submit:visible').count() == 1
        print('Public school login controls: PASS; no credentials, no login POST')
    finally:
        browser.close()
