#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script tự động build MC Launcher VN thành file .exe (Windows).

Yêu cầu:
  - Windows 10/11
  - Python 3.9+ (64-bit)
  - pip install pyinstaller

Chạy:
  python build_exe.py

Output:
  dist/MCLauncherVN/MCLauncherVN.exe   <- file thực thi chính
  dist/MCLauncherVN/                   <- thư mục phân phối (zip lại để chia sẻ)
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME    = "MCLauncherVN"
APP_VERSION = "0.3.0"
SCRIPT      = "mc_launcher.py"
SPEC_FILE   = "build_exe.spec"
DIST_DIR    = Path("dist")
BUILD_DIR   = Path("build")


def check_pyinstaller():
    try:
        import PyInstaller
        print(f"[OK] PyInstaller {PyInstaller.__version__} đã cài")
        return True
    except ImportError:
        return False


def install_pyinstaller():
    print("[...] Đang cài PyInstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller"])
    print("[OK] Đã cài PyInstaller")


def clean_old_build():
    for d in [DIST_DIR / APP_NAME, BUILD_DIR]:
        if d.exists():
            print(f"[...] Xóa thư mục cũ: {d}")
            shutil.rmtree(d)


def build():
    print(f"\n{'='*60}")
    print(f"   MC Launcher VN v{APP_VERSION} — Build .exe")
    print(f"{'='*60}\n")

    if platform.system() != "Windows":
        print("[!] CẢNH BÁO: Bạn đang chạy trên không phải Windows.")
        print("    File .exe chỉ có thể build trên Windows.")
        print("    Tiếp tục sẽ tạo file thực thi cho hệ điều hành hiện tại.\n")

    # Cài PyInstaller nếu chưa có
    if not check_pyinstaller():
        install_pyinstaller()

    # Dọn build cũ
    clean_old_build()

    # Build
    print("[...] Đang build, vui lòng đợi (1-3 phút)...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        SPEC_FILE,
    ]
    result = subprocess.run(cmd)

    if result.returncode != 0:
        print("\n[THẤT BẠI] Build không thành công. Xem lỗi ở trên.")
        sys.exit(1)

    exe_path = DIST_DIR / APP_NAME / f"{APP_NAME}.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\n{'='*60}")
        print(f"[THÀNH CÔNG] File .exe đã sẵn sàng!")
        print(f"  Đường dẫn : {exe_path.resolve()}")
        print(f"  Kích thước : {size_mb:.1f} MB")
        print(f"\n  Để chia sẻ: Zip toàn bộ thư mục dist/{APP_NAME}/ và gửi cho người dùng.")
        print(f"  Người dùng chỉ cần giải nén và chạy {APP_NAME}.exe — không cần cài Python.")
        print(f"{'='*60}\n")
    else:
        print(f"\n[THẤT BẠI] Không tìm thấy file .exe tại: {exe_path}")
        sys.exit(1)


if __name__ == "__main__":
    build()
