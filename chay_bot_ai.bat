@echo off
setlocal
cd /d "%~dp0"
chcp 65001 > nul
title Magic Survival AutoFarm - Kaggle AI Mode (Neural Value + Vision CNN)
echo ===============================================================
echo   MAGIC SURVIVAL AUTOFARM - CHẾ ĐỘ KAGGLE AI (NEURAL NETWORK)
echo   Sử dụng model: ai_models/skill_value_net.json + card_vision.npz
echo ===============================================================
echo.
call .\.venv\Scripts\activate.bat

:loop
echo [%date% %time%] Bắt đầu bot chế độ Kaggle AI...
python bot_cli.py 1 --build ai
if errorlevel 1 (
    echo.
    echo [%date% %time%] [!] Bot gặp sự cố hoặc mất kết nối. Tự động thử lại sau 5 giây...
    timeout /t 5 /nobreak > nul
    goto loop
)
echo.
echo [%date% %time%] [OK] Phiên chơi đã hoàn thành.
pause
