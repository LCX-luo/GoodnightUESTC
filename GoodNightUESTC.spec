# Build an unpack-and-run Windows directory using installed Microsoft Edge.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

project = Path(SPECPATH)
pw_data, pw_binaries, pw_imports = collect_all('playwright')
a = Analysis([str(project/'app.py')], pathex=[str(project), str(project/'vendor')],
             binaries=pw_binaries,
             datas=[(str(project/'static'), 'static'),
                    (str(project/'wechat_worker.py'), '.'),
                    (str(project/'README.md'), 'licenses'),
                    (str(project/'LICENSE'), 'licenses'),
                    (str(project/'vendor/THIRD_PARTY_NOTICES.md'), 'licenses'),
                    (str(project/'vendor/MoonUESTC-LICENSE'), 'licenses'),
                    (str(project/'vendor/third_party'), 'licenses/third_party')]+pw_data,
             hiddenimports=pw_imports, hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='GoodNightUESTC',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='GoodNightUESTC')
