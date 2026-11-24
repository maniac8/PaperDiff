@echo off
chcp 65001 >nul
cd /d "%~dp0paperdiff"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 launch_desktop.py --stop
) else (
  python launch_desktop.py --stop
)
timeout /t 2 /nobreak >nul
exit /b 0
