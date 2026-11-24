@echo off
chcp 65001 >nul
cd /d "%~dp0paperdiff"
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" /b pythonw launch_desktop.py --daemon
  exit /b 0
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 launch_desktop.py --daemon
  exit /b %errorlevel%
)
python launch_desktop.py --daemon
exit /b %errorlevel%
