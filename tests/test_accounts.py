import tempfile
import unittest
from app import create_app

BASE = 'http://127.0.0.1:8090'


class AccountIsolation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name)
        self.client = self.app.test_client()
        self.csrf = self.client.get('/api/status', base_url=BASE).json['csrf']

    def tearDown(self):
        self.temp.cleanup()

    def post(self, path, value, token=None):
        return self.client.post(path, json=value, base_url=BASE,
                                headers={'Origin':BASE,'X-CSRF-Token':token or self.csrf})

    def profile(self, name):
        result = self.post('/api/accounts', {'name':name})
        self.assertEqual(result.status_code, 201)
        identifier = result.json['profile']['id']
        status = self.client.get('/api/accounts/'+identifier+'/status',base_url=BASE)
        self.assertEqual(status.status_code, 200)
        self.assertIn('account_'+identifier, status.headers['Set-Cookie'])
        return identifier, status.json['csrf']

    def test_locations_and_csrf_are_isolated(self):
        a, token_a = self.profile('甲')
        b, token_b = self.profile('乙')
        point = {'name':'本人的位置','latitude':30.67,'longitude':104.09,'coordinate_system':'gcj02'}
        self.assertEqual(self.post('/api/accounts/'+a+'/location', point, token_b).status_code,403)
        self.assertEqual(self.post('/api/accounts/'+a+'/location', point, token_a).status_code,200)
        self.assertIsNone(self.client.get('/api/accounts/'+b+'/status',base_url=BASE).json['location'])
        self.assertIsNone(self.client.get('/api/status',base_url=BASE).json['location'])

    def test_authorization_page_does_not_expose_attendance_write(self):
        a, token = self.profile('本人')
        for action in ('checkin','checkin/prepare','unknown'):
            self.assertEqual(self.post('/api/accounts/'+a+'/'+action,{},token).status_code,404)

    def test_invalid_profile_and_cross_origin_cannot_create_or_route(self):
        self.assertEqual(self.client.post('/api/accounts',json={'name':'x'},base_url=BASE).status_code,403)
        self.assertEqual(self.post('/api/accounts/../../location',{}).status_code,404)
        self.assertEqual(self.post('/api/accounts/'+('a'*32)+'/location',{}).status_code,404)
        self.assertFalse(self.client.get('/api/accounts',base_url=BASE).json['schedulingEnabled'])

    def test_record_summary_never_returns_credentials(self):
        a, token = self.profile('本人')
        child = self.app.extensions['account_children'][a]
        store = child.extensions['local_store']
        store.save_session({'student_id':'202300000001','saved_at':123,'user_agent':'Synthetic',
                            'cookies':[{'name':'SESSION','value':'private-cookie'}]})
        value = {'student_id':'202300000001','last_verified_at':123,
                 'credentials':{'access_token':'private-access','refresh_token':'private-refresh','expires_at':456}}
        (store.directory/'wechat.enc').write_bytes(store.vault.seal(value,'wechat-authorization'))
        response = self.client.get('/api/accounts',base_url=BASE)
        text = response.get_data(as_text=True)
        for secret in ('private-cookie','private-access','private-refresh'):
            self.assertNotIn(secret,text)
        record = response.json['profiles'][0]
        self.assertTrue(record['wechatSaved'])
        self.assertEqual(record['verifiedAt'],123)

    def test_import_current_reencrypts_and_does_not_copy_ticket_or_duplicate(self):
        source = self.app.extensions['local_store']
        source.save_session({'student_id':'202300000001','saved_at':123,'user_agent':'Synthetic',
                             'cookies':[{'name':'SESSION','value':'private-cookie'}], 'operation_ticket':'t'*43})
        value = {'student_id':'202300000001','credentials':{'access_token':'private-access'}}
        (source.directory/'wechat.enc').write_bytes(source.vault.seal(value,'wechat-authorization'))
        response = self.post('/api/accounts/import-current',{})
        self.assertEqual(response.status_code,201)
        identifier = response.json['profile']['id']
        from core import LocalStore
        target = LocalStore(source.directory/'profiles'/identifier)
        self.assertNotIn('operation_ticket',target.session())
        self.assertEqual(target.session()['cookies'][0]['value'],'private-cookie')
        self.assertNotEqual(source.vault.key,target.vault.key)
        self.assertEqual(target.vault.open((target.directory/'wechat.enc').read_bytes(),'wechat-authorization'),value)
        self.assertTrue(self.post('/api/accounts/import-current',{}).json['existing'])

    def test_draft_requires_complete_credentials_and_explicit_save(self):
        a, token = self.profile('草稿')
        self.assertFalse(self.client.get('/api/accounts',base_url=BASE).json['profiles'][0]['ready'])
        self.assertEqual(self.post('/api/accounts/'+a+'/save',{'name':'正式账号'}).status_code,400)
        local=self.app.extensions['account_children'][a].extensions['local_store']
        local.save_session({'student_id':'202300000001','saved_at':123,'user_agent':'Synthetic','cookies':[]})
        value={'student_id':'202300000001','credentials':{'access_token':'synthetic'}}
        (local.directory/'wechat.enc').write_bytes(local.vault.seal(value,'wechat-authorization'))
        local.save_location({'name':'本人位置','latitude':30.67,'longitude':104.09,'coordinate_system':'gcj02'})
        self.assertFalse(self.client.get('/api/accounts',base_url=BASE).json['profiles'][0]['ready'])
        self.assertEqual(self.post('/api/accounts/'+a+'/save',{'name':'正式账号'}).status_code,400)
        value['last_verified_at']=123
        (local.directory/'wechat.enc').write_bytes(local.vault.seal(value,'wechat-authorization'))
        response=self.post('/api/accounts/'+a+'/save',{'name':'正式账号'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json['profile']['ready'])
        self.assertEqual(response.json['profile']['name'],'正式账号')

    def active_get(self, profile, action='status'):
        return self.client.get('/api/'+action,base_url=BASE,headers={'X-Account-ID':profile})

    def active_post(self, profile, action, value, token):
        return self.client.post('/api/'+action,json=value,base_url=BASE,
            headers={'Origin':BASE,'X-CSRF-Token':token,'X-Account-ID':profile})

    def test_unified_page_uses_per_profile_store_and_csrf(self):
        a,_=self.profile('甲');b,_=self.profile('乙')
        token_a=self.active_get(a).json['csrf'];token_b=self.active_get(b).json['csrf']
        point={'name':'本人位置','latitude':30.67,'longitude':104.09,'coordinate_system':'gcj02'}
        self.assertEqual(self.active_post(a,'location',point,self.csrf).status_code,403)
        self.assertEqual(self.active_post(a,'location',point,token_b).status_code,403)
        self.assertEqual(self.active_post(a,'location',point,token_a).status_code,200)
        self.assertIsNone(self.active_get(b).json['location'])
        self.assertIsNone(self.client.get('/api/status',base_url=BASE).json['location'])
        self.assertEqual(self.active_get(a).json['location']['name'],'本人位置')

    def test_unified_draft_cannot_submit_or_fall_back_to_another_account(self):
        a,_=self.profile('草稿');token=self.active_get(a).json['csrf']
        self.assertEqual(self.active_post(a,'checkin/prepare',{},token).status_code,409)
        self.assertEqual(self.active_post('f'*32,'location',{},token).status_code,404)
        self.assertEqual(self.active_get('../../','status').status_code,404)
        self.assertEqual(self.active_get(a,'accounts').status_code,404)
        self.assertEqual(self.client.post('/api/location',base_url=BASE,json={},
            headers={'X-Account-ID':a,'X-CSRF-Token':token,'Origin':'http://external.invalid'}).status_code,403)

    def test_saved_profile_can_prepare_only_its_own_confirmation(self):
        import json
        from unittest.mock import patch
        a,_=self.profile('本人');b,_=self.profile('另一人')
        store=self.app.extensions['account_children'][a].extensions['local_store']
        store.save_session({'student_id':'202300000001','saved_at':123,'user_agent':'Synthetic','cookies':[]})
        store.save_location({'name':'本人位置','latitude':30.67,'longitude':104.09,'coordinate_system':'gcj02'})
        index=store.directory.parent/'index.json';rows=json.loads(index.read_text('utf-8'))
        for row in rows:row['saved']=True
        index.write_text(json.dumps(rows),encoding='utf-8')
        token=self.active_get(a).json['csrf']
        with patch('app.prepare_checkin',return_value={'businessDate':'2026-10-26','address':'本人位置'}):
            response=self.active_post(a,'checkin/prepare',{},token)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json['confirmation'])
        token_b=self.active_get(b).json['csrf']
        self.assertEqual(self.active_post(b,'checkin',{'confirmation':response.json['confirmation'],'confirm':True,'actual_location_confirmed':True},token_b).status_code,400)
        wrong=self.active_post(a,'login',{'student_id':'202300000002'},token)
        self.assertEqual(wrong.status_code,409)
        self.assertEqual(store.session()['student_id'],'202300000001')

    def test_previous_account_page_redirects_to_unified_workspace(self):
        r=self.client.get('/accounts',base_url=BASE)
        self.assertEqual(r.status_code,302)
        self.assertEqual(r.headers['Location'],'/')


if __name__ == '__main__':
    unittest.main()
