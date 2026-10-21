@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
python bootstrap.py --install-only
if errorlevel 1 goto end
".venv\Scripts\python.exe" -m pip install "pyinstaller>=6.0,<7"
if errorlevel 1 goto end
".venv\Scripts\python.exe" -m PyInstaller --noconfirm GoodNightUESTC.spec
:end
pause
