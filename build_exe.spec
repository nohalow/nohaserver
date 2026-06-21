# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec file cho MC Launcher VN
# Cách dùng:
#   1. Cài PyInstaller:  pip install pyinstaller
#   2. Build .exe:       pyinstaller build_exe.spec
#   3. File .exe xuất hiện trong thư mục: dist/MCLauncherVN/
#
# Lưu ý: Phải chạy trên Windows để ra file .exe cho Windows

import sys
from pathlib import Path

APP_NAME    = "MCLauncherVN"
APP_VERSION = "0.3.0"
SCRIPT      = "mc_launcher.py"
ICON        = "assets/icon.ico"   # Đặt file icon .ico vào thư mục assets/ (tùy chọn)

# Kiểm tra icon có tồn tại không
icon_path = ICON if Path(ICON).exists() else None

a = Analysis(
    [SCRIPT],
    pathex=[],
    binaries=[],
    datas=[
        # Thêm assets nếu có: ("assets/", "assets/"),
    ],
    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.scrolledtext",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.simpledialog",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy", "pandas", "matplotlib", "scipy",
        "PIL", "cv2", "sklearn",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # False = ẩn cửa sổ cmd, chỉ hiện GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
    version_info=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
