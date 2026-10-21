@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
where py >nul 2>nul
if %errorlevel%==0 (py -3 bootstrap.py --install-only) else (python bootstrap.py --install-only)
pause
