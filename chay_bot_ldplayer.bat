@echo off
setlocal
cd /d "%~dp0"
chcp 65001 > nul
title Magic Survival AutoFarm - LDPlayer (ADB)
echo ===============================================================
echo     MAGIC SURVIVAL AUTOFARM - CHẾ ĐỘ 1: LDPLAYER (ADB)
echo     Chế độ: Chạy full không giới hạn (Auto-Restart 24/7)
echo ===============================================================
echo.
call .\.venv\Scripts\activate.bat

:loop
echo [%date% %time%] Bắt đầu tiến trình bot...
python bot_cli.py 1
if errorlevel 1 (
    echo.
    echo [%date% %time%] [!] Bot gặp sự cố lỗi hoặc mất kết nối. Tự động thử lại sau 5 giây...
    timeout /t 5 /nobreak > nul
    goto loop
)
echo.
echo [%date% %time%] [OK] Phiên chơi đã hoàn thành theo giới hạn thiết lập (6 tiếng).
pause
