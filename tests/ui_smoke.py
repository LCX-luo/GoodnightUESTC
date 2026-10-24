"""Exercise the localhost UI in Edge; never log in or submit to school."""
import json
import re
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from waitress import create_server
import tempfile
import threading
import time
from unittest.mock import patch
from core import LocalStore, now
from test_readonly import SNAPSHOT


def main():
    errors = []
    # A temporary app instance keeps QA points out of the user's saved location.
    with tempfile.TemporaryDirectory() as data, sync_playwright() as p:
        LocalStore(data).save_session(SNAPSHOT)
        server = create_server(create_app(data), host='127.0.0.1', port=8091, threads=4)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        browser = p.chromium.launch(channel='msedge', headless=True)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1200}, device_scale_factor=1)
            page.on('pageerror', lambda error: errors.append(str(error)))
            # The app pins its Origin/Host to 8090: route the test window to a temp
            # instance while retaining the normal user-visible origin.
            def proxy(route):
                response = route.fetch(url=route.request.url.replace(':8090', ':8091'),
                                       headers={**route.request.headers, 'host': '127.0.0.1:8090'})
                route.fulfill(response=response)
            page.route('http://127.0.0.1:8090/**', proxy)
            page.goto('http://127.0.0.1:8090/', wait_until='networkidle')
            page.locator('.leaflet-container').wait_for()
            assert abs(page.evaluate('() => map.getCenter().lat')-30.6752) < .001
            page.locator('#campus-qingshuihe').click()
            page.wait_for_timeout(350)
            assert abs(page.evaluate('() => map.getCenter().lng')-103.9313) < .001
            page.locator('#campus-shahe').click()
            page.wait_for_timeout(350)
            zoom = page.evaluate('() => map.getZoom()')
            scroll = page.evaluate('window.scrollY')
            page.locator('#map').hover()
            page.mouse.wheel(0, -240)
            page.wait_for_timeout(350)
            assert page.evaluate('() => map.getZoom()') > zoom
            assert page.evaluate('window.scrollY') == scroll
            page.locator('#campus-shahe').click()
            page.wait_for_timeout(350)
            expect(page.locator('#account-label')).to_contain_text(SNAPSHOT['student_id'])
            page.locator('#student-id').fill(SNAPSHOT['student_id'])
            page.locator('#password').fill('Synthetic-Password-Only')
            with patch('browser_login.BrowserLogin.start', return_value=None) as login:
                page.locator('#login-button').click()
                expect(page.locator('#login-button')).to_be_enabled()
                login.assert_called_once()
                expect(page.locator('#password')).to_have_value('Synthetic-Password-Only')
            page.locator('#password').fill('')
            expect(page.locator('.disclaimer')).to_contain_text('免责声明')
            page.locator('#map').click(position={'x': 250, 'y': 160})
            assert page.locator('#latitude').input_value()
            assert page.locator('#coordinate-system').input_value() == 'wgs84'
            page.locator('#place-name').fill('地图选点测试')
            page.locator('#save-location').click()
            page.locator('#converted').filter(has_text='GCJ-02：').wait_for()
            page.locator('#offline').click()
            page.get_by_text('离线自检通过', exact=True).wait_for()
            page.locator('details summary').click()
            result = json.loads(page.locator('#result-json').inner_text())
            assert result['schoolRequests'] == 0 and result['schoolWrites'] == 0
            page.locator('details summary').click()
            preview = {'businessDate': now().date().isoformat(), 'name': '合成测试位置', 'address': '合成测试地址',
                       'latitude': 30.7528, 'longitude': 103.9313, 'window': {'start': '21:00', 'end': '23:30'}}
            def slow_prepare(*args, **kwargs):
                kwargs['progress']('正在检查所选位置…')
                time.sleep(1.2)
                return preview
            def slow_submit(*args, **kwargs):
                kwargs['progress']('正在核对学校记录…')
                time.sleep(1.2)
                return {'mode': 'checkin', 'result': 'confirmed', 'confirmed': True, 'submitted': True, 'recordStatus': 'CHECKED_IN', 'apiCode': 0}
            with patch('app.prepare_checkin', side_effect=slow_prepare), patch('app.submit_checkin', side_effect=slow_submit) as submit:
                page.locator('#prepare-checkin').click()
                expect(page.locator('#prepare-checkin')).to_contain_text('正在')
                page.locator('#checkin-dialog').wait_for(state='visible')
                assert page.locator('#submit-checkin').is_disabled()
                page.locator('#confirm-location').check()
                page.locator('#submit-checkin').click()
                expect(page.locator('#checkin-progress')).to_be_visible()
                page.locator('#checkin-state').filter(has_text='学校接受且记录已确认').wait_for()
                submit.assert_called_once()
            # Screenshot an unsubmitted UI, not the synthetic success result.
            page.reload(wait_until='networkidle')
            page.screenshot(path=str(ROOT/'preview-desktop.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            page.reload(wait_until='domcontentloaded')
            expect(page.locator('#latitude')).to_have_value(re.compile('.+'))
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(ROOT/'preview-mobile.png'), full_page=True)
            assert not errors, errors
            print('Edge UI PASS: map, saved location, offline test, mocked confirmation, mobile; real school writes=0')
        finally:
            browser.close()
            server.close()
            thread.join(timeout=3)


if __name__ == '__main__':
    main()
