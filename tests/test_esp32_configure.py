import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
class StandaloneConfiguration(unittest.TestCase):
    def module(self,directory):
        spec=importlib.util.spec_from_file_location('standalone_configure',ROOT/'esp32/configure.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.ROOT=Path(directory);return module
    def test_local_configuration_generates_distinct_keys_and_omits_wifi_from_phone(self):
        with tempfile.TemporaryDirectory() as d:
            module=self.module(d)
            with patch('builtins.input',side_effect=['SyntheticSSID','mqtts://broker.example.invalid:8883']),patch('getpass.getpass',return_value='synthetic-wifi-password'),patch('builtins.print'):
                module.main()
            phone=json.loads((Path(d)/'phone-management.local.json').read_text('utf-8'))
            self.assertEqual(len(bytes.fromhex(phone['encryptionKeyHex'])),32)
            self.assertEqual(len(bytes.fromhex(phone['signingKeyHex'])),32)
            self.assertNotEqual(phone['encryptionKeyHex'],phone['signingKeyHex'])
            self.assertNotIn('synthetic-wifi-password',json.dumps(phone))
            self.assertIn('CONFIG_GN_WIFI_SSID=',(Path(d)/'sdkconfig.defaults.local').read_text('utf-8'))
    def test_existing_configuration_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'sdkconfig.defaults.local';path.write_text('original',encoding='utf-8');module=self.module(d)
            with self.assertRaises(SystemExit):module.main()
            self.assertEqual(path.read_text('utf-8'),'original')
    def test_inline_broker_credentials_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            module=self.module(d)
            with patch('builtins.input',side_effect=['SyntheticSSID','mqtt://user:secret@broker.example.invalid']),patch('getpass.getpass',return_value='synthetic'),self.assertRaises(SystemExit):module.main()
            self.assertFalse((Path(d)/'sdkconfig.defaults.local').exists())
if __name__=='__main__':unittest.main()
