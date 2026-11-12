@echo off
setlocal
cd /d "%~dp0"
chcp 65001 > nul
title Magic Survival - AutoFarm CLI Terminal
echo ===============================================================
echo     MAGIC SURVIVAL AUTOFARM - CHAY TRUC TIEP TERMINAL
echo ===============================================================
echo.
call .\.venv\Scripts\activate.bat
python bot_cli.py %*
pause
