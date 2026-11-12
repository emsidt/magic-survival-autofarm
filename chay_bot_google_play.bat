@echo off
setlocal
cd /d "%~dp0"
chcp 65001 > nul
title Magic Survival AutoFarm - Google Play Games PC
echo ===============================================================
echo     MAGIC SURVIVAL AUTOFARM - CHẾ ĐỘ 2: GOOGLE PLAY GAMES PC
echo ===============================================================
echo.
call .\.venv\Scripts\activate.bat
python bot_cli.py 2
if errorlevel 1 pause
