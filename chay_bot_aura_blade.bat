@echo off
setlocal
cd /d "%~dp0"
chcp 65001 > nul
title Magic Survival AutoFarm - Giáo Án Aura Blade (DEM)
echo ===============================================================
echo   MAGIC SURVIVAL AUTOFARM - CHẾ ĐỘ GIÁO ÁN: AURA BLADE (DEM)
echo   Nhân vật: Summoner | LDPlayer (ADB) | Giới hạn: 6 giờ / phiên
echo   Lộ trình: Spirit (Magic Blade) + Electric Shock (Superconductivity)
echo             -> Aura Blade -> Overmind -> Deus Ex Machina (DEM)
echo ===============================================================
echo.
call .\.venv\Scripts\activate.bat

:loop
echo [%date% %time%] Bắt đầu bot chế độ Aura Blade (DEM)...
python bot_cli.py 1 --build aura_blade
if errorlevel 1 (
    echo.
    echo [%date% %time%] [!] Bot gặp sự cố lỗi hoặc mất kết nối. Tự động thử lại sau 5 giây...
    timeout /t 5 /nobreak > nul
    goto loop
)
echo.
echo [%date% %time%] [OK] Phiên chơi đã hoàn thành theo giới hạn thiết lập (6 tiếng).
pause
