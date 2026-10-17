@echo off
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -m app.hyperion_app
) else (
  python -m app.hyperion_app
)
if errorlevel 1 pause
