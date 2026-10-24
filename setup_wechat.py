"""Optional Windows authorization runtime, isolated from the desktop Python."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PIN = 'f8a93c3bc4d62cea879b76560c49c9646387b386'
SOURCE = 'https://github.com/MioYiSama/moon-uestc.git'


def main():
    private = ROOT / 'private-data'
    tools = private / 'wechat-tools'
    uv = tools / 'Scripts/uv.exe'
    if not uv.exists():
        subprocess.check_call([sys.executable, '-m', 'venv', str(tools)])
        subprocess.check_call([str(tools / 'Scripts/python.exe'), '-m', 'pip', 'install', 'uv==0.13.5'])
    source = private / 'moon-uestc-reference'
    if not source.exists():
        subprocess.check_call(['git', 'clone', SOURCE, str(source)])
        subprocess.check_call(['git', '-C', str(source), 'checkout', '--detach', PIN])
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if head != PIN:
        raise RuntimeError('Reference checkout is not the reviewed version; refusing to modify it.')
    environment = {**os.environ, 'UV_PYTHON_INSTALL_DIR': str(private / 'python'),
                   'UV_CACHE_DIR': str(private / 'uv-cache')}
    runtime = private / 'wechat-runtime'
    if not (runtime / 'Scripts/python.exe').exists():
        subprocess.check_call([str(uv), 'venv', '--python', '3.13', str(runtime)], env=environment)
    subprocess.check_call([str(uv), 'pip', 'install', '--python', str(runtime / 'Scripts/python.exe'),
                           '-e', str(source)], env=environment)
    print('WeChat authorization runtime installed. Restart the desktop app.')


if __name__ == '__main__':
    main()
