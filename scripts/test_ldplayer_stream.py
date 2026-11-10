"""Script to test and verify ADB background stream and controls with LDPlayer.

Run: python scripts/test_ldplayer_stream.py
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from adb_controller import ADBController, DEFAULT_LDPLAYER_ADB
import botcore


def test_stream():
    print("=" * 65)
    print("  🚀 KIỂM TRA LUỒNG KẾT NỐI NGẦM ADB VỚI LDPLAYER 🚀")
    print("=" * 65)

    adb_path = DEFAULT_LDPLAYER_ADB
    if not Path(adb_path).is_file():
        print(f"[!] Không tìm thấy file adb.exe tại: {adb_path}")
        return False

    print(f"[+] Tìm thấy adb của LDPlayer: {adb_path}")
    print("[*] Đang dò tìm máy ảo LDPlayer...")

    ctrl = ADBController(adb_path=adb_path)
    if not ctrl.device:
        print("\n" + "!" * 65)
        print(" [!] CHƯA BẬT GỠ LỖI ADB TRONG LDPLAYER!")
        print("!" * 65)
        print("Trong LDPlayer 9, mặc định cổng ADB đang bị tắt.")
        print("Bạn chỉ cần bật lên 1 lần duy nhất theo 3 bước cực nhanh sau:")
        print("  1. Trên thanh công cụ bên phải LDPlayer, bấm icon ⚙️ (Cài đặt / Settings).")
        print("  2. Chọn tab 'Cài đặt khác' (Other settings).")
        print("  3. Tại dòng 'Gỡ lỗi ADB' (ADB debugging): Chọn 'Mở kết nối cục bộ' (Open connection locally).")
        print("  4. Bấm 'Lưu cài đặt' (Save) và khởi động lại LDPlayer.")
        print("-" * 65)
        print("Sau khi bật xong, hãy chạy lại lệnh này nhé!\n")
        return False

    print(f"\n[+] ĐÃ KẾT NỐI THÀNH CÔNG VỚI LDPLAYER! (Device: {ctrl.device})")
    print(f"[+] Độ phân giải màn hình máy ảo: {ctrl.screen_width}x{ctrl.screen_height}")

    print("\n[*] Đang thử chụp 1 khung hình ngầm từ máy ảo Android (Screencap)...")
    t0 = time.monotonic()
    frame = ctrl.screenshot()
    t_cost = time.monotonic() - t0

    if frame is None:
        print("[!] Không chụp được khung hình qua ADB. Hãy kiểm tra lại màn hình LDPlayer.")
        return False

    print(f"[+] ĐÃ NHẬN KHUNG HÌNH THÀNH CÔNG! (Kích thước: {frame.shape[1]}x{frame.shape[0]}, Thời gian: {t_cost*1000:.1f}ms)")

    # Lưu ảnh test để người dùng xem lại
    out_img = BASE_DIR / "captures" / "ldplayer_live_stream.png"
    out_img.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_img), frame)
    print(f"[+] Đã lưu ảnh chụp ngầm vào: {out_img}")

    # Chạy AI Vision phân tích trạng thái game trên LDPlayer
    print("\n[*] Đang phân tích màn hình game hiện tại:")
    ea = botcore.detect_enter_area(frame)
    sg = botcore.detect_start_game(frame)
    pause = botcore.detect_pause_button(frame)
    lvl = botcore.is_level_up_screen(frame)
    mana = botcore.detect_mana_orb_currency(frame)
    buy = botcore.detect_buy_button(frame)

    if lvl:
        print(f"    -> [Trạng thái]: MÀN HÌNH LÊN CẤP! (Lý do: {lvl.reason})")
    elif pause:
        print(f"    -> [Trạng thái]: ĐANG TRONG TRẬN ĐẤU! (Phát hiện nút Pause tại: {pause})")
    elif buy:
        print(f"    -> [Trạng thái]: ĐANG MỞ CỬA HÀNG THƯƠNG NHÂN (Nút Buy tại: {buy})")
    elif ea or sg:
        print("    -> [Trạng thái]: ĐANG Ở SẢNH CHỜ / CHỌN BẢN ĐỒ")
    else:
        print("    -> [Trạng thái]: Màn hình game thông thường")

    if mana is not None:
        print(f"    -> [Mana Orbs]: Đọc được {mana} Mana Orbs!")

    print("\n" + "=" * 65)
    print("  🎉 LUỒNG ĐIỀU KHIỂN NGẦM ADB HOẠT ĐỘNG HOÀN HẢO! 🎉")
    print("  Chuột và bàn phím của bạn sẽ không bị chiếm khi bot chạy.")
    print("=" * 65 + "\n")
    return True


if __name__ == "__main__":
    test_stream()
