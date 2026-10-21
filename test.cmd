@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
python bootstrap.py --install-only
if errorlevel 1 goto end
".venv\Scripts\python.exe" -m unittest discover -s tests -v
:end
pause
