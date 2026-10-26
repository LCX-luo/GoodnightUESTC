"""Local encrypted fixture tests; no network, serial device or real accounts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from core import LocalStore
from esp32 import provision


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profiles = self.root / 'private-data/profiles'
        self.profiles.mkdir(parents=True)
        self.index = []
        self.root_patch = patch.object(provision, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.temporary.cleanup)

    def profile(self, name, verified, *, student='202300000001', bound=None, saved=True, complete=True, session=None, lat=30.67):
        self.index.append({'id': name, 'saved': saved})
        store = LocalStore(self.profiles / name)
        store.save_session({'student_id': student, 'saved_at': verified + 100,
                            'cookies': [{'name': 'SESSION', 'value': session or name,
                                         'domain': 'jzsz.uestc.edu.cn', 'path': '/'}]})
        store.save_location({'name': name, 'latitude': lat, 'longitude': 104.09,
                             'coordinate_system': 'gcj02'})
        credentials = {'openid': 'synthetic-openid-' + name, 'access_token': 'synthetic-access-' + name,
                       'refresh_token': 'synthetic-refresh-' + name, 'expires_at': 2000000000}
        if not complete:
            credentials.pop('refresh_token')
        record = {'student_id': bound or student, 'last_verified_at': verified, 'credentials': credentials}
        (store.directory / 'wechat.enc').write_bytes(store.vault.seal(record, 'wechat-authorization'))
        (self.profiles / 'index.json').write_text(json.dumps(self.index), encoding='utf-8')
        return store

    def test_latest_verified_profile_wins_as_a_complete_bundle(self):
        self.profile('new', 300, session='synthetic-new-session', lat=30.68)
        self.profile('old', 100, session='synthetic-old-session', lat=30.66)
        result = provision.configuration()
        self.assertFalse(result['enabled'])
        self.assertEqual(len(result['accounts']), 1)
        account = result['accounts'][0]
        self.assertEqual(account['schoolSession'], 'synthetic-new-session')
        self.assertEqual(account['wechat']['refresh_token'], 'synthetic-refresh-new')
        self.assertAlmostEqual(account['location']['latitude'], 30.68)

    def test_later_invalid_or_unbound_entries_cannot_replace_verified_bundle(self):
        self.profile('verified', 200)
        self.profile('newer-incomplete', 400, complete=False)
        self.profile('newer-wrong-binding', 500, bound='202300000002')
        self.profile('newer-draft', 600, saved=False)
        account = provision.configuration()['accounts'][0]
        self.assertEqual(account['schoolSession'], 'verified')
        self.assertEqual(account['wechat']['openid'], 'synthetic-openid-verified')

    def test_duplicate_profiles_do_not_count_toward_four_unique_account_limit(self):
        for number in range(5):
            self.profile('copy' + str(number), number + 1)
        self.profile('second', 100, student='202300000002')
        result = provision.configuration(enable=True)
        self.assertTrue(result['enabled'])
        self.assertEqual(len(result['accounts']), 2)
        only = provision.configuration(only='202300000002')
        self.assertEqual(len(only['accounts']), 1)
        self.assertEqual(only['accounts'][0]['schoolSession'], 'second')


if __name__ == '__main__':
    unittest.main()
