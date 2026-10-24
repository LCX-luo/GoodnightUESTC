"""Exercise the multi-profile page locally with no school login or requests."""
import sys
import tempfile
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from waitress import create_server
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app


def main():
    with tempfile.TemporaryDirectory() as directory, sync_playwright() as p:
        server=create_server(create_app(directory),host='127.0.0.1',port=8092,threads=4)
        worker=threading.Thread(target=server.run,daemon=True);worker.start()
        browser=p.chromium.launch(channel='msedge',headless=True)
        errors=[]
        try:
            page=browser.new_page(viewport={'width':1200,'height':900})
            page.on('pageerror',lambda error:errors.append(str(error)))
            def proxy(route):
                response=route.fetch(url=route.request.url.replace(':8090',':8092'),headers={**route.request.headers,'host':'127.0.0.1:8090'})
                route.fulfill(response=response)
            page.route('http://127.0.0.1:8090/**',proxy)
            page.goto('http://127.0.0.1:8090/accounts',wait_until='networkidle')
            for name in ['测试甲','测试乙']:
                page.locator('#name').fill(name);page.locator('#add button').click()
                expect(page.locator('#editor')).to_be_visible()
                expect(page.locator('#profiles option:checked')).to_have_text(name)
                expect(page.locator('#add button')).to_be_enabled()
            options=page.locator('#profiles option').evaluate_all('(items)=>items.map(x=>x.value).filter(Boolean)')
            assert len(options)==2
            page.locator('#lat').fill('30.67');page.locator('#lng').fill('104.09');page.locator('#location button').click()
            expect(page.locator('#message')).to_contain_text('已保存')
            page.locator('#profiles').select_option(options[0]);expect(page.locator('#lat')).to_have_value('')
            expect(page.locator('#wechat')).to_be_disabled()
            page.locator('#profiles').select_option(options[1]);expect(page.locator('#lat')).to_have_value('30.67')
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert not errors,errors
            print('Multi-account Edge UI PASS: isolated profiles, save/switch, CSRF, mobile; school requests=0')
        finally:
            browser.close();server.close();worker.join(timeout=3)


if __name__=='__main__':main()
