@echo off
rem Fetch yakkun.com team articles (runs at logon; can also be run by hand)
cd /d "%~dp0"
timeout /t 90 /nobreak >nul
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set BR=%%b
git pull --rebase --autostash origin %BR% >> ..\logs\study\yakkun\run.log 2>&1
python yakkun_fetch.py --push >> ..\logs\study\yakkun\run.log 2>&1
