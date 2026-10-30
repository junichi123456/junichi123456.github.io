@echo off
rem Fetch yakkun.com team articles (runs at logon; can also be run by hand)
rem Thursday only: skip on other days. Pass "force" to run on any day.
cd /d "%~dp0"
if /i not "%~1"=="force" (
  powershell -NoProfile -Command "exit [int](Get-Date).DayOfWeek"
  if not errorlevel 4 exit /b 0
  if errorlevel 5 exit /b 0
)
timeout /t 90 /nobreak >nul
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set BR=%%b
git pull --rebase --autostash origin %BR% >> ..\logs\study\yakkun\run.log 2>&1
python yakkun_fetch.py --push >> ..\logs\study\yakkun\run.log 2>&1
