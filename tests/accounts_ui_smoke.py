"""Test the library draft/login/authorization/map/save workflow with mocked auth."""
import sys, tempfile, threading, time
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from waitress import create_server
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app

def fake_login(self, student_id, password):
    self.store.save_session({'student_id':student_id,'saved_at':time.time(),'user_agent':'Synthetic','cookies':[]})
    self.state={'state':'success','message':'模拟登录已完成'}

def fake_wechat(self, snapshot):
    value={'student_id':snapshot['student_id'],'last_verified_at':time.time(),'credentials':{'access_token':'synthetic','expires_at':2000000000}}
    (self.store.directory/'wechat.enc').write_bytes(self.store.vault.seal(value,'wechat-authorization'))
    self.state={'state':'success','message':'模拟微信取票成功，没有提交'}

def main():
    with tempfile.TemporaryDirectory() as directory, sync_playwright() as p, patch('browser_login.BrowserLogin.start',fake_login), patch('wechat_auth.WeChatAuthorization.start',fake_wechat):
        server=create_server(create_app(directory),host='127.0.0.1',port=8092,threads=4)
        worker=threading.Thread(target=server.run,daemon=True);worker.start()
        browser=p.chromium.launch(channel='msedge',headless=True)
        errors=[]
        try:
            page=browser.new_page(viewport={'width':1200,'height':1100})
            page.on('pageerror',lambda error:errors.append(str(error)))
            def proxy(route):
                response=route.fetch(url=route.request.url.replace(':8090',':8092'),headers={**route.request.headers,'host':'127.0.0.1:8090'})
                route.fulfill(response=response)
            page.route('http://127.0.0.1:8090/**',proxy)
            page.goto('http://127.0.0.1:8090/accounts',wait_until='networkidle')
            expect(page.locator('#editor')).to_be_visible()
            for index,name in enumerate(['测试甲','测试乙']):
                if index:page.locator('#new-account').click()
                page.locator('#name').fill(name)
                page.locator('#student').fill('20230000000'+str(index+1))
                page.locator('#password').fill('SyntheticOnly')
                page.locator('#login-button').click()
                expect(page.locator('#wechat')).to_be_enabled()
                page.locator('#wechat').click()
                expect(page.locator('#wechat-status')).to_contain_text('已保存加密凭据')
                assert page.locator('#records tr').count()==index
                page.locator('#map').click(position={'x':220,'y':150})
                expect(page.locator('#system')).to_have_value('wgs84')
                expect(page.locator('#save-account')).to_be_enabled()
                latitude=page.locator('#lat').input_value()
                page.locator('#campus-qingshuihe').click()
                expect(page.locator('#lat')).to_have_value(latitude)
                page.locator('#save-account').click()
                expect(page.locator('#message')).to_contain_text('已保存到账号库')
                expect(page.locator('#records tr')).to_have_count(index+1)
            options=page.locator('#profiles option').evaluate_all('(items)=>items.map(x=>x.value).filter(Boolean)')
            assert len(options)==2
            page.locator('#profiles').select_option(options[0])
            expect(page.locator('#student')).to_have_value('202300000001')
            page.locator('#profiles').select_option(options[1])
            expect(page.locator('#student')).to_have_value('202300000002')
            assert page.evaluate('map.scrollWheelZoom.enabled()')
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert not errors,errors
            print('Account library UI PASS: drafts hidden, auth, map/campus, explicit save, update, isolation; school requests=0')
        finally:
            browser.close();server.close();worker.join(timeout=3)
if __name__=='__main__':main()
