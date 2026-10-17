@echo off
rem やっくん構築記事の取得（PC起動時に自動実行。手動で実行してもよい）
chcp 65001 >nul
cd /d "%~dp0"
timeout /t 90 /nobreak >nul
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set BR=%%b
git pull --rebase --autostash origin %BR% >> ..\logs\study\yakkun\run.log 2>&1
python yakkun_fetch.py --push >> ..\logs\study\yakkun\run.log 2>&1
