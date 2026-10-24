"""Prepare the four reviewed protocol modules, excluding upstream app/login code.

Fetched code is generated build input, not committed or relicensed by this project.
The only adaptation removes Pydantic imports used exclusively in type annotations.
"""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
PIN = 'f8a93c3bc4d62cea879b76560c49c9646387b386'
MODULES = ('_wechat_crypto.py', '_wechat_wire.py', '_wechat_dns.py', '_wechat_mmtls.py')


def main():
    source = ROOT / 'private-data/moon-uestc-reference'
    if not source.exists():
        subprocess.check_call(['git', 'clone', 'https://github.com/MioYiSama/moon-uestc.git', str(source)])
        subprocess.check_call(['git', '-C', str(source), 'checkout', '--detach', PIN])
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != PIN:
        raise RuntimeError('Unexpected upstream commit')
    subprocess.check_call(['git', '-C', str(source), 'diff', '--exit-code', 'HEAD', '--',
                           *('src/moon_uestc/' + name for name in MODULES)])
    target = ROOT / 'android/app/build/generated/wechatPython/wechat_protocol'
    target.mkdir(parents=True, exist_ok=True)
    manifest = {'repository': 'https://github.com/MioYiSama/moon-uestc', 'commit': PIN, 'sha256': {}}
    for name in MODULES:
        raw = (source / 'src/moon_uestc' / name).read_bytes()
        manifest['sha256'][name] = hashlib.sha256(raw).hexdigest()
        text = raw.decode('utf-8').replace('from pydantic import JsonValue', 'from typing import Any as JsonValue')
        (target / name).write_text(text, encoding='utf-8')
    (target / '__init__.py').write_text('', encoding='utf-8')
    (target / 'wechat_models.py').write_text('''class WeChatError(RuntimeError):
    pass
class WeChatAuthorizationError(WeChatError):
    pass
class WeChatProtocolError(WeChatError):
    pass
''', encoding='utf-8')
    (target / 'SOURCE.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Prepared reviewed Android protocol inputs; no credentials or user data included.')


if __name__ == '__main__':
    main()
