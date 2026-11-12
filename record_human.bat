@echo off
setlocal
cd /d "%~dp0"
chcp 65001 > nul
title Magic Survival - Human Expert Demonstration Recorder
echo ===============================================================
echo     MAGIC SURVIVAL - BỘ GHI HÌNH CHUYÊN GIA (HUMAN RECORDER)
echo ===============================================================
echo.
echo Bạn sẽ tự tay chơi game 100%%. Tool chỉ chạy ngầm quan sát:
echo - Ghi lại toàn bộ kỹ năng và rương bạn đã chọn.
echo - Ghi lại thời gian sống sót của bạn (ví dụ 45 phút).
echo - Nạp trực tiếp kinh nghiệm và build của bạn vào não AI!
echo.
echo Đang kích hoạt môi trường Python...
call .\.venv\Scripts\activate.bat
python record_human_play.py
pause

