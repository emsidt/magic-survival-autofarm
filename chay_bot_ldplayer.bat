@echo off
setlocal
cd /d "%~dp0"
chcp 65001 > nul
title Magic Survival AutoFarm - LDPlayer (ADB)
echo ===============================================================
echo     MAGIC SURVIVAL AUTOFARM - CHẾ ĐỘ 1: LDPLAYER (ADB)
echo ===============================================================
echo.
call .\.venv\Scripts\activate.bat
python bot_cli.py 1
if errorlevel 1 pause
