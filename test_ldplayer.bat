@echo off
setlocal
cd /d "%~dp0"
chcp 65001 > nul
title Magic Survival - Kiem tra luong ADB LDPlayer
echo ===============================================================
echo     KIEM TRA KET NOI NGAM ADB VOI LDPLAYER
echo ===============================================================
echo.
call .\.venv\Scripts\activate.bat
python scripts/test_ldplayer_stream.py
pause
