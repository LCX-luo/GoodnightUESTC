"""Standard-library-only first-run setup. No Docker, Node.js or browser download."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    if sys.version_info < (3, 10):
        print('Python 3.10 or newer is required. https://www.python.org/downloads/')
        return 1
    env = ROOT / '.venv'
    python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        print('Creating local Python environment...')
        subprocess.check_call([sys.executable, '-m', 'venv', str(env)])
    digest = hashlib.sha256((ROOT/'requirements.txt').read_bytes()).hexdigest()
    stamp = env/'requirements.sha256'
    if not stamp.exists() or stamp.read_text('ascii') != digest:
        print('Installing project dependencies (first run only)...')
        subprocess.check_call([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                               '-r', str(ROOT/'requirements.txt')])
        stamp.write_text(digest, encoding='ascii')
    if '--install-only' in sys.argv:
        return 0
    return subprocess.call([str(python), str(ROOT/'app.py')], cwd=ROOT,
                           env={**os.environ, 'PYTHONUTF8': '1'})


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except subprocess.CalledProcessError:
        print('Setup failed. Check your network and run start.cmd again.')
        raise SystemExit(1)
