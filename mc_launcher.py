#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MC Launcher VN v0.3.0 — Công cụ tạo & chạy Minecraft Server ngay trên máy tính.

Tính năng:
  - Chọn loại server: Paper (khuyên dùng) hoặc Vanilla
  - Chọn phiên bản Minecraft từ danh sách mới nhất (Mojang / PaperMC)
  - Quản lý nhiều profile server (lưu & tải cấu hình)
  - Chọn RAM bằng thanh trượt (tự nhận RAM máy)
  - Tự động tải Java JAR, tạo eula.txt, server.properties
  - Nhập lệnh trực tiếp vào console server đang chạy
  - Khởi động / Dừng / Restart server
  - Tích hợp playit.gg để bạn bè vào chơi không cần mở port
  - Tự động phát hiện nhiều phiên bản Java đã cài

Yêu cầu: Python 3.9+  (chỉ dùng thư viện chuẩn)
Chạy:    python mc_launcher.py
"""

import ctypes
import json
import os
import platform
import queue
import subprocess
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

# ---------------------------------------------------------------------------
# Hằng số / cấu hình
# ---------------------------------------------------------------------------

APP_NAME    = "MC Launcher VN"
APP_VERSION = "0.3.0"

USER_AGENT = f"MCLauncherVN/{APP_VERSION} (+https://github.com/example/mc-launcher-vn)"

MOJANG_MANIFEST_URL  = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
PAPER_API_BASE       = "https://fill.papermc.io/v3/projects/paper"
PLAYIT_RELEASES_API  = "https://api.github.com/repos/playit-cloud/playit-agent/releases/latest"
PLAYIT_DOWNLOAD_PAGE = "https://playit.gg/download"
PLAYIT_SECRET_KEY_PAGE = "https://playit.gg/account/agents/new-key"

PLAYIT_FALLBACK_WINDOWS = (
    "https://github.com/playit-cloud/playit-agent/releases/latest/download/"
    "playit-windows-x86_64-signed.exe"
)

DEFAULT_BASE_DIR  = str(Path.home() / "MCLauncherVN")
PROFILES_FILE     = str(Path.home() / "MCLauncherVN" / ".profiles.json")

# Màu sắc giao diện tối (Dark mode)
COLORS = {
    "bg":           "#1a1a2e",
    "bg2":          "#16213e",
    "bg3":          "#0f3460",
    "fg":           "#e0e0e0",
    "fg2":          "#a0a0b0",
    "accent":       "#00d084",
    "accent2":      "#00b894",
    "danger":       "#e74c3c",
    "warn":         "#f39c12",
    "console_bg":   "#0d1117",
    "console_fg":   "#58d68d",
    "console_info": "#5dade2",
    "console_warn": "#f0b27a",
    "console_err":  "#ec7063",
}


# ---------------------------------------------------------------------------
# Hàm tiện ích (không phụ thuộc GUI)
# ---------------------------------------------------------------------------

def get_total_ram_gb() -> int:
    """Lấy tổng RAM máy (GB). Trả về 8 nếu không xác định được."""
    system = platform.system()
    try:
        if system == "Windows":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength",               ctypes.c_ulong),
                    ("dwMemoryLoad",           ctypes.c_ulong),
                    ("ullTotalPhys",           ctypes.c_ulonglong),
                    ("ullAvailPhys",           ctypes.c_ulonglong),
                    ("ullTotalPageFile",       ctypes.c_ulonglong),
                    ("ullAvailPageFile",       ctypes.c_ulonglong),
                    ("ullTotalVirtual",        ctypes.c_ulonglong),
                    ("ullAvailVirtual",        ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore
            return max(1, round(stat.ullTotalPhys / (1024 ** 3)))
        elif system == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        return max(1, round(kb / (1024 ** 2)))
        elif system == "Darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"])
            return max(1, round(int(out.strip()) / (1024 ** 3)))
    except Exception:
        pass
    return 8


def _no_window_flag():
    """Flag để ẩn cửa sổ cmd trên Windows khi chạy subprocess."""
    if platform.system() == "Windows":
        return subprocess.CREATE_NO_WINDOW
    return 0


def find_java_installations() -> list[tuple[str, str]]:
    """
    Tìm tất cả Java đã cài (path, version_string).
    Trả về list có ít nhất 1 phần tử; tuple đầu tiên luôn là java mặc định (PATH).
    """
    candidates: list[tuple[str, str]] = []

    def probe(java_bin: str) -> tuple[str, str] | None:
        try:
            r = subprocess.run(
                [java_bin, "-version"],
                capture_output=True, text=True, timeout=8,
                creationflags=_no_window_flag(),
            )
            raw = (r.stderr or r.stdout or "").strip()
            first = raw.splitlines()[0] if raw else "Unknown"
            return java_bin, first
        except Exception:
            return None

    # 1. java trong PATH
    r = probe("java")
    if r:
        candidates.append(r)

    # 2. Các vị trí phổ biến trên Windows
    if platform.system() == "Windows":
        search_roots = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
            Path(r"C:\Program Files\Eclipse Adoptium"),
            Path(r"C:\Program Files\Microsoft"),
        ]
        for root in search_roots:
            if root.exists():
                for subdir in root.iterdir():
                    if subdir.is_dir() and any(
                        kw in subdir.name.lower() for kw in ("java", "jdk", "jre", "adoptium", "temurin", "zulu")
                    ):
                        for jbin in ["bin/java.exe", "bin/java"]:
                            candidate_path = str(subdir / jbin)
                            if os.path.isfile(candidate_path):
                                r2 = probe(candidate_path)
                                if r2 and r2[0] not in {c[0] for c in candidates}:
                                    candidates.append(r2)

    return candidates if candidates else [("java", "Không tìm thấy Java")]


def check_java() -> tuple[bool, str | None]:
    """Kiểm tra nhanh Java trong PATH."""
    try:
        r = subprocess.run(
            ["java", "-version"],
            capture_output=True, text=True, timeout=10,
            creationflags=_no_window_flag(),
        )
        raw = (r.stderr or r.stdout or "").strip()
        first = raw.splitlines()[0] if raw else "Không rõ phiên bản"
        return True, first
    except Exception:
        return False, None


def fetch_json(url: str, headers: dict | None = None, timeout: int = 20):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_file(url: str, dest_path: str, headers: dict | None = None,
                  progress_cb=None, timeout: int = 60) -> None:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 256 * 1024
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as out_file:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)


def _version_sort_key(v: str):
    parts = []
    for p in v.replace("-", ".").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def get_vanilla_release_versions(limit: int = 30):
    data = fetch_json(MOJANG_MANIFEST_URL)
    releases = [v for v in data["versions"] if v.get("type") == "release"]
    return [(v["id"], v["url"]) for v in releases[:limit]]


def get_vanilla_jar_url(version_meta_url: str) -> str:
    data = fetch_json(version_meta_url)
    return data["downloads"]["server"]["url"]


def get_paper_versions(limit: int = 30):
    data = fetch_json(PAPER_API_BASE, headers={"User-Agent": USER_AGENT})
    all_versions: list[str] = []
    for group_versions in data.get("versions", {}).values():
        all_versions.extend(group_versions)
    all_versions = sorted(set(all_versions), key=_version_sort_key, reverse=True)
    return all_versions[:limit]


def get_paper_stable_build(version: str):
    url = f"{PAPER_API_BASE}/versions/{version}/builds"
    data = fetch_json(url, headers={"User-Agent": USER_AGENT})
    for build in data:
        if build.get("channel") == "STABLE":
            dl = build["downloads"]["server:default"]
            return dl["url"], dl["name"]
    if data:
        dl = data[0]["downloads"]["server:default"]
        return dl["url"], dl["name"]
    return None, None


def get_playit_download_url() -> str:
    try:
        data = fetch_json(PLAYIT_RELEASES_API, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        })
        for asset in data.get("assets", []):
            name = asset.get("name", "").lower()
            if "windows" in name and name.endswith(".exe") and "signed" in name:
                return asset["browser_download_url"]
        for asset in data.get("assets", []):
            name = asset.get("name", "").lower()
            if "windows" in name and name.endswith(".exe"):
                return asset["browser_download_url"]
    except Exception:
        pass
    return PLAYIT_FALLBACK_WINDOWS


# ---------------------------------------------------------------------------
# Quản lý Profile
# ---------------------------------------------------------------------------

DEFAULT_PROFILE = {
    "name":        "Server Mặc Định",
    "base_dir":    DEFAULT_BASE_DIR,
    "server_type": "paper",
    "version":     "",
    "ram":         min(4, max(1, get_total_ram_gb() // 2)),
    "online_mode": True,
    "port":        "25565",
    "java_bin":    "java",
    "jar_filename": None,
    "jvm_flags":   "-XX:+UseG1GC -XX:+ParallelRefProcEnabled",
}


def load_profiles() -> list[dict]:
    try:
        if os.path.exists(PROFILES_FILE):
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    return data
    except Exception:
        pass
    return [dict(DEFAULT_PROFILE)]


def save_profiles(profiles: list[dict]) -> None:
    os.makedirs(os.path.dirname(PROFILES_FILE), exist_ok=True)
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# GUI chính
# ---------------------------------------------------------------------------

class MCLauncherApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME}  v{APP_VERSION}")
        self.root.geometry("960x700")
        self.root.minsize(800, 600)
        self.root.configure(bg=COLORS["bg"])

        self.log_queue:    "queue.Queue[tuple[str,str]]" = queue.Queue()
        self.server_process:  subprocess.Popen | None = None
        self.playit_process:  subprocess.Popen | None = None
        self._playit_exe_path: str | None = None

        # Profiles
        self.profiles     = load_profiles()
        self.profile_idx  = 0
        self._profile_loading = False

        # Tk variables (sẽ được đồng bộ với profile khi chọn)
        self.base_dir_var    = tk.StringVar()
        self.server_type_var = tk.StringVar()
        self.version_var     = tk.StringVar()
        self.ram_var         = tk.IntVar()
        self.online_mode_var = tk.BooleanVar()
        self.port_var        = tk.StringVar()
        self.java_bin_var    = tk.StringVar()
        self.jvm_flags_var   = tk.StringVar()
        self.playit_secret_var = tk.StringVar()

        self._jar_filename: str | None = None
        self._versions_cache: dict[str, list] = {"paper": [], "vanilla": []}
        self._java_installations: list[tuple[str, str]] = []

        self._apply_dark_style()
        self._build_ui()
        self._load_profile(0)
        self._poll_log_queue()
        threading.Thread(target=self._init_async, daemon=True).start()

    # ------------------------------------------------------------------ style

    def _apply_dark_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        bg, bg2, fg, acc = COLORS["bg"], COLORS["bg2"], COLORS["fg"], COLORS["accent"]
        style.configure(".", background=bg, foreground=fg, fieldbackground=bg2,
                        insertcolor=fg, selectbackground=acc, selectforeground="#000",
                        borderwidth=1, relief="flat")
        style.configure("TFrame",        background=bg)
        style.configure("TLabel",        background=bg, foreground=fg)
        style.configure("TLabelframe",   background=bg, foreground=acc)
        style.configure("TLabelframe.Label", background=bg, foreground=acc, font=("Segoe UI", 9, "bold"))
        style.configure("TNotebook",     background=bg2, borderwidth=0)
        style.configure("TNotebook.Tab", background=bg2, foreground=fg, padding=[12, 6])
        style.map("TNotebook.Tab",
                  background=[("selected", COLORS["bg3"])],
                  foreground=[("selected", acc)])
        style.configure("TButton",    background=COLORS["bg3"], foreground=fg, padding=[8, 4])
        style.map("TButton",
                  background=[("active", acc), ("disabled", bg2)],
                  foreground=[("active", "#000"), ("disabled", COLORS["fg2"])])
        style.configure("Accent.TButton",  background=acc, foreground="#000", padding=[10, 5])
        style.map("Accent.TButton",  background=[("active", COLORS["accent2"])])
        style.configure("Danger.TButton",  background=COLORS["danger"], foreground="#fff", padding=[8, 4])
        style.map("Danger.TButton",  background=[("active", "#c0392b")])
        style.configure("TRadiobutton",    background=bg, foreground=fg)
        style.configure("TCheckbutton",    background=bg, foreground=fg)
        style.configure("TCombobox",  fieldbackground=bg2, foreground=fg, background=bg2)
        style.configure("TEntry",     fieldbackground=bg2, foreground=fg, insertcolor=fg)
        style.configure("TScale",     background=bg, troughcolor=bg2)
        style.configure("TProgressbar", troughcolor=bg2, background=acc)
        style.configure("TSeparator", background=COLORS["bg3"])

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self.root, bg=COLORS["bg2"], height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text=f"  ⛏  {APP_NAME}", bg=COLORS["bg2"],
                 fg=COLORS["accent"], font=("Segoe UI", 16, "bold")).pack(side="left", padx=12, pady=8)
        tk.Label(hdr, text=f"v{APP_VERSION}", bg=COLORS["bg2"],
                 fg=COLORS["fg2"], font=("Segoe UI", 9)).pack(side="left")
        ttk.Button(hdr, text="Trang chủ", command=lambda: webbrowser.open("https://github.com/example/mc-launcher-vn")).pack(side="right", padx=8, pady=10)

        # Main paned: left profile panel + right notebook
        main = tk.PanedWindow(self.root, orient="horizontal",
                              bg=COLORS["bg"], sashwidth=4, sashrelief="flat")
        main.pack(fill="both", expand=True, padx=0, pady=0)

        # --- Left: profile list ---
        left = tk.Frame(main, bg=COLORS["bg2"], width=200)
        main.add(left, minsize=160)
        tk.Label(left, text="SERVER PROFILES", bg=COLORS["bg2"],
                 fg=COLORS["accent"], font=("Segoe UI", 8, "bold")).pack(pady=(10, 4), padx=8, anchor="w")

        self.profile_listbox = tk.Listbox(
            left, bg=COLORS["bg3"], fg=COLORS["fg"],
            selectbackground=COLORS["accent"], selectforeground="#000",
            borderwidth=0, highlightthickness=0,
            font=("Segoe UI", 9), relief="flat",
        )
        self.profile_listbox.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.profile_listbox.bind("<<ListboxSelect>>", self._on_profile_select)

        pf_btn = tk.Frame(left, bg=COLORS["bg2"])
        pf_btn.pack(fill="x", padx=6, pady=(0, 8))
        ttk.Button(pf_btn, text="+ Thêm",    command=self._add_profile).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(pf_btn, text="Xóa",       command=self._delete_profile, style="Danger.TButton").pack(side="left", fill="x", expand=True)

        ttk.Button(left, text="Lưu profile", command=self._save_current_profile).pack(
            fill="x", padx=6, pady=(0, 8))

        self._refresh_profile_list()

        # --- Right: notebook + console ---
        right = tk.Frame(main, bg=COLORS["bg"])
        main.add(right)

        notebook = ttk.Notebook(right)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)

        self.tab_server = ttk.Frame(notebook)
        self.tab_advanced = ttk.Frame(notebook)
        self.tab_playit = ttk.Frame(notebook)
        notebook.add(self.tab_server,   text="  Server  ")
        notebook.add(self.tab_advanced, text="  Cài đặt nâng cao  ")
        notebook.add(self.tab_playit,   text="  Playit.gg  ")

        self._build_server_tab(self.tab_server)
        self._build_advanced_tab(self.tab_advanced)
        self._build_playit_tab(self.tab_playit)

        # Console frame
        console_frame = tk.LabelFrame(right, text=" Console ", bg=COLORS["bg"],
                                      fg=COLORS["accent"], font=("Segoe UI", 8, "bold"))
        console_frame.pack(fill="both", expand=False, padx=6, pady=(0, 6))

        self.log_text = scrolledtext.ScrolledText(
            console_frame, height=10,
            bg=COLORS["console_bg"], fg=COLORS["console_fg"],
            insertbackground="#fff", selectbackground=COLORS["accent"],
            font=("Consolas", 9) if platform.system() == "Windows" else ("Monospace", 9),
            borderwidth=0, relief="flat",
        )
        self.log_text.pack(fill="both", expand=True, padx=4, pady=(4, 0))
        self.log_text.configure(state="disabled")
        self.log_text.tag_configure("INFO", foreground=COLORS["console_info"])
        self.log_text.tag_configure("WARN", foreground=COLORS["console_warn"])
        self.log_text.tag_configure("ERR",  foreground=COLORS["console_err"])
        self.log_text.tag_configure("OK",   foreground=COLORS["accent"])

        # Command input
        cmd_row = tk.Frame(console_frame, bg=COLORS["console_bg"])
        cmd_row.pack(fill="x", padx=4, pady=4)
        tk.Label(cmd_row, text=">", bg=COLORS["console_bg"],
                 fg=COLORS["accent"], font=("Consolas", 10, "bold")).pack(side="left")
        self.cmd_entry = tk.Entry(
            cmd_row, bg=COLORS["bg2"], fg=COLORS["console_fg"],
            insertbackground=COLORS["accent"], relief="flat",
            font=("Consolas", 9),
        )
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.cmd_entry.bind("<Return>", self._send_server_command)
        ttk.Button(cmd_row, text="Gửi", command=self._send_server_command).pack(side="left")
        ttk.Button(cmd_row, text="Xóa log", command=self._clear_log).pack(side="left", padx=(4, 0))

    def _build_server_tab(self, parent):
        pad = {"padx": 10, "pady": 6}

        # Java status
        java_frame = ttk.LabelFrame(parent, text="Java")
        java_frame.pack(fill="x", **pad)
        jrow = ttk.Frame(java_frame)
        jrow.pack(fill="x", padx=8, pady=6)
        self.java_status_label = ttk.Label(jrow, text="Đang kiểm tra Java...")
        self.java_status_label.pack(side="left", fill="x", expand=True)
        self.java_combo = ttk.Combobox(jrow, textvariable=self.java_bin_var,
                                        state="readonly", width=28)
        self.java_combo.pack(side="left", padx=6)
        ttk.Button(jrow, text="Tải Java (Adoptium)",
                   command=lambda: webbrowser.open("https://adoptium.net/")).pack(side="left")

        # Thư mục server
        dir_frame = ttk.LabelFrame(parent, text="Thư mục server")
        dir_frame.pack(fill="x", **pad)
        drow = ttk.Frame(dir_frame)
        drow.pack(fill="x", padx=8, pady=6)
        ttk.Entry(drow, textvariable=self.base_dir_var).pack(side="left", fill="x", expand=True)
        ttk.Button(drow, text="Chọn...",    command=self._choose_dir).pack(side="left", padx=4)
        ttk.Button(drow, text="Mở thư mục", command=self._open_dir).pack(side="left")

        # Loại server & phiên bản
        type_frame = ttk.LabelFrame(parent, text="Loại server & phiên bản")
        type_frame.pack(fill="x", **pad)
        rrow = ttk.Frame(type_frame)
        rrow.pack(fill="x", padx=8, pady=(8, 2))
        ttk.Radiobutton(rrow, text="Paper  (khuyên dùng — hỗ trợ plugin, Geyser, tối ưu lag)",
                         variable=self.server_type_var, value="paper",
                         command=self._on_type_change).pack(side="left")
        ttk.Radiobutton(rrow, text="Vanilla  (nguyên bản)",
                         variable=self.server_type_var, value="vanilla",
                         command=self._on_type_change).pack(side="left", padx=(20, 0))
        vrow = ttk.Frame(type_frame)
        vrow.pack(fill="x", padx=8, pady=(2, 8))
        ttk.Label(vrow, text="Phiên bản:").pack(side="left")
        self.version_combo = ttk.Combobox(vrow, textvariable=self.version_var,
                                           state="readonly", width=22)
        self.version_combo.pack(side="left", padx=8)
        ttk.Button(vrow, text="Tải lại danh sách",
                   command=lambda: threading.Thread(target=self._load_versions_async, daemon=True).start()
                   ).pack(side="left")

        # RAM
        total_ram = get_total_ram_gb()
        ram_frame = ttk.LabelFrame(parent, text=f"RAM cấp cho server  (máy bạn có ~{total_ram} GB)")
        ram_frame.pack(fill="x", **pad)
        rram = ttk.Frame(ram_frame)
        rram.pack(fill="x", padx=8, pady=6)
        max_ram = max(2, total_ram)
        self.ram_scale = ttk.Scale(rram, from_=1, to=max_ram, orient="horizontal",
                                    command=self._on_ram_change)
        self.ram_scale.set(self.ram_var.get())
        self.ram_scale.pack(side="left", fill="x", expand=True)
        self.ram_value_label = ttk.Label(rram, text=f"{self.ram_var.get()} GB", width=8)
        self.ram_value_label.pack(side="left", padx=8)

        # Tuỳ chọn mạng
        opt_frame = ttk.LabelFrame(parent, text="Mạng")
        opt_frame.pack(fill="x", **pad)
        orow = ttk.Frame(opt_frame)
        orow.pack(fill="x", padx=8, pady=6)
        ttk.Checkbutton(orow, text="Yêu cầu tài khoản Minecraft bản quyền (online-mode)",
                         variable=self.online_mode_var).pack(side="left")
        ttk.Label(orow, text="   Cổng:").pack(side="left")
        ttk.Entry(orow, textvariable=self.port_var, width=8).pack(side="left")

        # Nút hành động
        act = ttk.Frame(parent)
        act.pack(fill="x", **pad)
        self.btn_install = ttk.Button(act, text="① Tải & Cài đặt", style="Accent.TButton",
                                       command=self._on_install_clicked)
        self.btn_install.pack(side="left", padx=4)
        self.btn_start = ttk.Button(act, text="▶ Khởi động",
                                     command=self._on_start_clicked, state="disabled")
        self.btn_start.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(act, text="■ Dừng", style="Danger.TButton",
                                    command=self._on_stop_clicked, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        self.btn_restart = ttk.Button(act, text="↺ Restart",
                                       command=self._on_restart_clicked, state="disabled")
        self.btn_restart.pack(side="left", padx=4)

        self.install_progress = ttk.Progressbar(parent, mode="determinate")
        self.install_progress.pack(fill="x", padx=10, pady=(0, 6))

        # Server status indicator
        self.server_status_var = tk.StringVar(value="● Đã dừng")
        self.server_status_label = tk.Label(parent, textvariable=self.server_status_var,
                                             bg=COLORS["bg"], fg=COLORS["danger"],
                                             font=("Segoe UI", 9, "bold"))
        self.server_status_label.pack(anchor="w", padx=12)

    def _build_advanced_tab(self, parent):
        pad = {"padx": 10, "pady": 8}

        jvm_frame = ttk.LabelFrame(parent, text="JVM Flags bổ sung")
        jvm_frame.pack(fill="x", **pad)
        ttk.Label(jvm_frame,
                  text="Các flag được thêm vào sau -Xmx/-Xms. Mặc định tối ưu cho Paper/G1GC:").pack(
            anchor="w", padx=8, pady=(6, 2))
        ttk.Entry(jvm_frame, textvariable=self.jvm_flags_var).pack(
            fill="x", padx=8, pady=(0, 8))

        tip = ttk.LabelFrame(parent, text="Mẹo tối ưu")
        tip.pack(fill="x", **pad)
        tips_text = (
            "• RAM Paper khuyên dùng: 4–8 GB cho 5–20 người chơi\n"
            "• Dùng Java 21+ cho Minecraft 1.21 trở lên để tốt nhất\n"
            "• Với Paper, thêm flag: -XX:MaxGCPauseMillis=200 -XX:G1HeapRegionSize=4M\n"
            "• Nếu server bị lag, giảm view-distance trong server.properties\n"
            "• Mở rộng server.properties bằng cách mở thư mục server"
        )
        ttk.Label(tip, text=tips_text, justify="left", wraplength=720).pack(
            padx=8, pady=8, anchor="w")

        open_props = ttk.Frame(parent)
        open_props.pack(fill="x", **pad)
        ttk.Button(open_props, text="Mở server.properties",
                   command=self._open_server_properties).pack(side="left")
        ttk.Button(open_props, text="Mở thư mục plugins",
                   command=self._open_plugins_dir).pack(side="left", padx=8)
        ttk.Button(open_props, text="Mở thư mục server",
                   command=self._open_dir).pack(side="left")

    def _build_playit_tab(self, parent):
        pad = {"padx": 10, "pady": 8}

        info = ttk.Label(parent, justify="left", wraplength=820, text=(
            "Playit.gg giúp bạn bè vào được server của bạn mà KHÔNG cần mở port hay IP tĩnh "
            "(rất hữu ích với mạng Viettel gói gia đình dùng CGNAT).\n\n"
            "Cách dùng:\n"
            "  1. Bấm 'Tải Playit.gg' (chỉ cần làm 1 lần)\n"
            "  2. Bấm 'Chạy Playit.gg' — lần đầu sẽ in link claim https://playit.gg/claim/xxxx trong Console\n"
            "  3. Mở link đó bằng trình duyệt, đăng nhập và tạo tunnel về cổng Minecraft (mặc định 25565)\n"
            "  4. Playit sẽ cấp địa chỉ dạng xxxx.joinmc.link — gửi cho bạn bè là xong!"
        ))
        info.pack(fill="x", **pad)

        sk_frame = ttk.LabelFrame(parent, text="(Nâng cao) Secret Key — tránh claim lại mỗi lần")
        sk_frame.pack(fill="x", **pad)
        skrow = ttk.Frame(sk_frame)
        skrow.pack(fill="x", padx=8, pady=6)
        ttk.Entry(skrow, textvariable=self.playit_secret_var, show="*").pack(
            side="left", fill="x", expand=True)
        ttk.Button(skrow, text="Tạo Secret Key",
                   command=lambda: webbrowser.open(PLAYIT_SECRET_KEY_PAGE)).pack(side="left", padx=6)

        act = ttk.Frame(parent)
        act.pack(fill="x", **pad)
        self.btn_playit_download = ttk.Button(act, text="① Tải Playit.gg", style="Accent.TButton",
                                               command=self._on_playit_download_clicked)
        self.btn_playit_download.pack(side="left", padx=4)
        self.btn_playit_run = ttk.Button(act, text="▶ Chạy Playit.gg",
                                          command=self._on_playit_run_clicked, state="disabled")
        self.btn_playit_run.pack(side="left", padx=4)
        self.btn_playit_stop = ttk.Button(act, text="■ Dừng Playit.gg", style="Danger.TButton",
                                           command=self._on_playit_stop_clicked, state="disabled")
        self.btn_playit_stop.pack(side="left", padx=4)
        ttk.Button(act, text="Mở trang tải thủ công",
                   command=lambda: webbrowser.open(PLAYIT_DOWNLOAD_PAGE)).pack(side="left", padx=12)

    # --------------------------------------------------------------- helpers

    def _log(self, msg: str, tag: str = ""):
        self.log_queue.put((msg if msg.endswith("\n") else msg + "\n", tag))

    def _poll_log_queue(self):
        try:
            while True:
                line, tag = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                if tag:
                    self.log_text.insert("end", line, tag)
                else:
                    self.log_text.insert("end", line)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(120, self._poll_log_queue)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _send_server_command(self, event=None):
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
        if self.server_process and self.server_process.poll() is None:
            try:
                assert self.server_process.stdin is not None
                self.server_process.stdin.write(cmd + "\n")
                self.server_process.stdin.flush()
                self._log(f"> {cmd}", "OK")
            except Exception as e:
                self._log(f"[Lỗi gửi lệnh] {e}", "ERR")
        else:
            self._log("[Server chưa chạy]", "WARN")
        self.cmd_entry.delete(0, "end")

    def _set_server_status(self, running: bool):
        if running:
            self.server_status_var.set("● Đang chạy")
            self.server_status_label.configure(fg=COLORS["accent"])
        else:
            self.server_status_var.set("● Đã dừng")
            self.server_status_label.configure(fg=COLORS["danger"])

    # ---------------------------------------------------------- profile mgmt

    def _refresh_profile_list(self):
        self.profile_listbox.delete(0, "end")
        for p in self.profiles:
            self.profile_listbox.insert("end", p.get("name", "Profile"))
        if 0 <= self.profile_idx < len(self.profiles):
            self.profile_listbox.selection_set(self.profile_idx)
            self.profile_listbox.see(self.profile_idx)

    def _on_profile_select(self, event=None):
        sel = self.profile_listbox.curselection()
        if sel and sel[0] != self.profile_idx:
            self.profile_idx = sel[0]
            self._load_profile(self.profile_idx)

    def _load_profile(self, idx: int):
        if idx < 0 or idx >= len(self.profiles):
            return
        self._profile_loading = True
        p = self.profiles[idx]
        self.base_dir_var.set(p.get("base_dir", DEFAULT_BASE_DIR))
        self.server_type_var.set(p.get("server_type", "paper"))
        self.version_var.set(p.get("version", ""))
        ram = p.get("ram", 4)
        self.ram_var.set(ram)
        if hasattr(self, "ram_scale"):
            self.ram_scale.set(ram)
            self.ram_value_label.configure(text=f"{ram} GB")
        self.online_mode_var.set(p.get("online_mode", True))
        self.port_var.set(p.get("port", "25565"))
        self.java_bin_var.set(p.get("java_bin", "java"))
        self.jvm_flags_var.set(p.get("jvm_flags", DEFAULT_PROFILE["jvm_flags"]))
        self._jar_filename = p.get("jar_filename")
        if self._jar_filename and hasattr(self, "btn_start"):
            self.btn_start.configure(state="normal")
        self._profile_loading = False
        self._on_type_change()

    def _save_current_profile(self):
        if self.profile_idx < 0 or self.profile_idx >= len(self.profiles):
            return
        p = self.profiles[self.profile_idx]
        p["base_dir"]    = self.base_dir_var.get()
        p["server_type"] = self.server_type_var.get()
        p["version"]     = self.version_var.get()
        p["ram"]         = self.ram_var.get()
        p["online_mode"] = self.online_mode_var.get()
        p["port"]        = self.port_var.get()
        p["java_bin"]    = self.java_bin_var.get()
        p["jvm_flags"]   = self.jvm_flags_var.get()
        p["jar_filename"] = self._jar_filename
        save_profiles(self.profiles)
        self._log("✅ Đã lưu profile.", "OK")

    def _add_profile(self):
        name = simpledialog.askstring("Thêm profile", "Tên profile mới:", parent=self.root)
        if not name:
            return
        new_p = dict(DEFAULT_PROFILE)
        new_p["name"]     = name
        new_p["base_dir"] = str(Path.home() / "MCLauncherVN" / name.replace(" ", "_"))
        self.profiles.append(new_p)
        self.profile_idx = len(self.profiles) - 1
        save_profiles(self.profiles)
        self._refresh_profile_list()
        self._load_profile(self.profile_idx)

    def _delete_profile(self):
        if len(self.profiles) <= 1:
            messagebox.showwarning(APP_NAME, "Bạn cần giữ ít nhất 1 profile.", parent=self.root)
            return
        name = self.profiles[self.profile_idx].get("name", "profile")
        if not messagebox.askyesno(APP_NAME, f"Xóa profile '{name}'?", parent=self.root):
            return
        self.profiles.pop(self.profile_idx)
        self.profile_idx = max(0, self.profile_idx - 1)
        save_profiles(self.profiles)
        self._refresh_profile_list()
        self._load_profile(self.profile_idx)

    # --------------------------------------------------------- async init

    def _init_async(self):
        self._refresh_java_status()
        self._load_versions_async()

    def _refresh_java_status(self):
        self._log("Đang quét các phiên bản Java...", "INFO")
        installations = find_java_installations()
        self._java_installations = installations
        display_values = []
        bin_values     = []
        for (java_bin, version_str) in installations:
            label = f"{os.path.basename(java_bin)}  |  {version_str[:60]}"
            display_values.append(label)
            bin_values.append(java_bin)
        self._java_bin_values = bin_values

        def update():
            self.java_combo.configure(values=display_values)
            current_bin = self.java_bin_var.get()
            if current_bin in bin_values:
                idx = bin_values.index(current_bin)
                self.java_combo.current(idx)
            elif bin_values:
                self.java_combo.current(0)
                self.java_bin_var.set(bin_values[0])
            self.java_combo.bind("<<ComboboxSelected>>", self._on_java_selected)

            ok, info = check_java()
            if ok:
                self.java_status_label.configure(
                    text=f"✅ Java OK: {(info or '')[:80]}", foreground=COLORS["accent"])
            else:
                self.java_status_label.configure(
                    text="❌ Không tìm thấy Java — Tải Adoptium bên phải", foreground=COLORS["danger"])

        self.root.after(0, update)

    def _on_java_selected(self, event=None):
        idx = self.java_combo.current()
        if 0 <= idx < len(self._java_bin_values):
            self.java_bin_var.set(self._java_bin_values[idx])

    # -------------------------------------------------------- version load

    def _load_versions_async(self):
        try:
            self._log("Đang lấy danh sách phiên bản Paper...", "INFO")
            paper_versions = get_paper_versions()
            self._versions_cache["paper"] = paper_versions
            self._log(f"  -> Tìm thấy {len(paper_versions)} phiên bản Paper.", "OK")
        except Exception as e:
            self._log(f"[Lỗi] Không lấy được danh sách Paper: {e}", "ERR")

        try:
            self._log("Đang lấy danh sách phiên bản Vanilla...", "INFO")
            vanilla_versions = get_vanilla_release_versions()
            self._versions_cache["vanilla"] = [v[0] for v in vanilla_versions]
            self._versions_cache["_vanilla_urls"] = dict(vanilla_versions)   # type: ignore
            self._log(f"  -> Tìm thấy {len(vanilla_versions)} phiên bản Vanilla.", "OK")
        except Exception as e:
            self._log(f"[Lỗi] Không lấy được danh sách Vanilla: {e}", "ERR")

        self.root.after(0, self._on_type_change)

    def _on_type_change(self):
        if self._profile_loading:
            return
        stype = self.server_type_var.get()
        versions = self._versions_cache.get(stype, [])
        self.version_combo.configure(values=versions)
        cur = self.version_var.get()
        if versions:
            if cur not in versions:
                self.version_var.set(versions[0])
        else:
            self.version_var.set("")

    # ------------------------------------------------------------ helpers UI

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.base_dir_var.get(), parent=self.root)
        if d:
            self.base_dir_var.set(d)

    def _open_dir(self):
        d = self.base_dir_var.get()
        os.makedirs(d, exist_ok=True)
        self._open_path(d)

    def _open_server_properties(self):
        p = os.path.join(self.base_dir_var.get(), "server.properties")
        if not os.path.exists(p):
            messagebox.showinfo(APP_NAME, "server.properties chưa tồn tại. Hãy cài đặt server trước.", parent=self.root)
            return
        self._open_path(p)

    def _open_plugins_dir(self):
        d = os.path.join(self.base_dir_var.get(), "plugins")
        os.makedirs(d, exist_ok=True)
        self._open_path(d)

    def _open_path(self, path: str):
        try:
            if platform.system() == "Windows":
                os.startfile(path)   # type: ignore
            elif platform.system() == "Darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception as e:
            self._log(f"[Lỗi] Không mở được: {e}", "ERR")

    def _on_ram_change(self, value):
        ram = int(float(value))
        self.ram_var.set(ram)
        self.ram_value_label.configure(text=f"{ram} GB")

    # -------------------------------------------------------------- install

    def _on_install_clicked(self):
        threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self):
        self.btn_install.configure(state="disabled")
        try:
            server_type = self.server_type_var.get()
            version     = self.version_var.get()
            if not version:
                self._log("[Lỗi] Bạn chưa chọn phiên bản Minecraft.", "ERR")
                return

            server_dir = self.base_dir_var.get()
            os.makedirs(server_dir, exist_ok=True)

            self._log(f"Đang lấy link tải {server_type} {version}...", "INFO")
            if server_type == "paper":
                url, filename = get_paper_stable_build(version)
                if not url:
                    self._log("[Lỗi] Không tìm thấy build Paper cho phiên bản này.", "ERR")
                    return
            else:
                urls = self._versions_cache.get("_vanilla_urls", {})
                meta_url = urls.get(version)
                if not meta_url:
                    self._log("[Lỗi] Không tìm thấy phiên bản Vanilla này.", "ERR")
                    return
                url = get_vanilla_jar_url(meta_url)
                filename = "server.jar"

            self._jar_filename = filename
            dest_path = os.path.join(server_dir, filename)
            self._log(f"Đang tải {filename} ...", "INFO")

            def progress(downloaded, total):
                if total:
                    pct = downloaded / total * 100
                    self.root.after(0, lambda: self.install_progress.configure(value=pct))

            download_file(url, dest_path, progress_cb=progress)
            self.root.after(0, lambda: self.install_progress.configure(value=100))
            self._log(f"Đã tải xong: {dest_path}", "OK")

            # eula.txt
            with open(os.path.join(server_dir, "eula.txt"), "w") as f:
                f.write("eula=true\n")
            self._log("Đã tạo eula.txt.", "OK")

            # server.properties (chỉ ghi nếu chưa tồn tại)
            props_path = os.path.join(server_dir, "server.properties")
            if not os.path.exists(props_path):
                port = self.port_var.get() or "25565"
                with open(props_path, "w") as f:
                    f.write(f"online-mode={'true' if self.online_mode_var.get() else 'false'}\n")
                    f.write(f"server-port={port}\n")
                    f.write("motd=\\u00a7a\\u00a7lMC Launcher VN\\u00a7r Server\n")
                    f.write("view-distance=10\n")
                    f.write("simulation-distance=10\n")
                self._log("Đã tạo server.properties.", "OK")

            self._log("✅ Cài đặt hoàn tất! Bấm 'Khởi động' để chạy server.", "OK")

            # Lưu profile
            if self.profile_idx < len(self.profiles):
                self.profiles[self.profile_idx]["jar_filename"] = self._jar_filename
                save_profiles(self.profiles)

            self.root.after(0, lambda: self.btn_start.configure(state="normal"))
        except urllib.error.URLError as e:
            self._log(f"[Lỗi mạng] Không tải được: {e}", "ERR")
        except Exception as e:
            self._log(f"[Lỗi] {e}", "ERR")
        finally:
            self.root.after(0, lambda: self.btn_install.configure(state="normal"))

    # --------------------------------------------------------------- server

    def _on_start_clicked(self):
        if not self._jar_filename:
            messagebox.showwarning(APP_NAME, "Bạn cần Tải & Cài đặt server trước.", parent=self.root)
            return
        threading.Thread(target=self._start_server_worker, daemon=True).start()

    def _start_server_worker(self):
        server_dir = self.base_dir_var.get()
        ram        = self.ram_var.get()
        jar        = self._jar_filename
        java_bin   = self.java_bin_var.get() or "java"
        jvm_flags  = self.jvm_flags_var.get().split()
        cmd = [java_bin, f"-Xmx{ram}G", f"-Xms{ram}G"] + jvm_flags + ["-jar", jar, "nogui"]
        self._log(f"Khởi động: {' '.join(cmd)}", "INFO")
        try:
            self.server_process = subprocess.Popen(
                cmd, cwd=server_dir,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                creationflags=_no_window_flag() if platform.system() == "Windows" else 0,
            )
        except FileNotFoundError:
            self._log("[Lỗi] Không tìm thấy lệnh 'java'. Hãy cài Java trước.", "ERR")
            return
        except Exception as e:
            self._log(f"[Lỗi] Không khởi động được server: {e}", "ERR")
            return

        self.root.after(0, lambda: self.btn_start.configure(state="disabled"))
        self.root.after(0, lambda: self.btn_stop.configure(state="normal"))
        self.root.after(0, lambda: self.btn_restart.configure(state="normal"))
        self.root.after(0, lambda: self._set_server_status(True))

        assert self.server_process.stdout is not None
        for line in self.server_process.stdout:
            stripped = line.rstrip("\n")
            tag = ""
            lo = stripped.lower()
            if "error" in lo or "exception" in lo or "fatal" in lo:
                tag = "ERR"
            elif "warn" in lo:
                tag = "WARN"
            elif "done" in lo or "started" in lo:
                tag = "OK"
            self._log(stripped, tag)

        self._log("[Server đã dừng]", "WARN")
        self.root.after(0, lambda: self.btn_start.configure(state="normal"))
        self.root.after(0, lambda: self.btn_stop.configure(state="disabled"))
        self.root.after(0, lambda: self.btn_restart.configure(state="disabled"))
        self.root.after(0, lambda: self._set_server_status(False))

    def _on_stop_clicked(self):
        if self.server_process and self.server_process.poll() is None:
            try:
                assert self.server_process.stdin is not None
                self.server_process.stdin.write("stop\n")
                self.server_process.stdin.flush()
                self._log("Đã gửi lệnh 'stop'...", "WARN")
            except Exception:
                self.server_process.terminate()

    def _on_restart_clicked(self):
        if self.server_process and self.server_process.poll() is None:
            self._on_stop_clicked()
            threading.Thread(target=self._wait_and_restart, daemon=True).start()

    def _wait_and_restart(self):
        if self.server_process:
            self.server_process.wait()
        import time; time.sleep(1)
        self._log("Đang khởi động lại server...", "INFO")
        self._start_server_worker()

    # -------------------------------------------------------------- playit

    def _on_playit_download_clicked(self):
        threading.Thread(target=self._playit_download_worker, daemon=True).start()

    def _playit_download_worker(self):
        self.btn_playit_download.configure(state="disabled")
        try:
            if platform.system() != "Windows":
                self._log(
                    "[Lưu ý] Tải tự động chỉ hỗ trợ Windows. Dùng nút 'Mở trang tải thủ công'.", "WARN")
                return
            url  = get_playit_download_url()
            dest = os.path.join(self.base_dir_var.get(), "playit-agent.exe")
            self._log(f"Đang tải playit agent: {url}", "INFO")
            download_file(url, dest)
            self._playit_exe_path = dest
            self._log(f"Đã tải xong: {dest}", "OK")
            self.root.after(0, lambda: self.btn_playit_run.configure(state="normal"))
        except Exception as e:
            self._log(f"[Lỗi] Không tải được playit: {e}", "ERR")
        finally:
            self.root.after(0, lambda: self.btn_playit_download.configure(state="normal"))

    def _on_playit_run_clicked(self):
        threading.Thread(target=self._playit_run_worker, daemon=True).start()

    def _playit_run_worker(self):
        exe = self._playit_exe_path
        if not exe or not os.path.exists(exe):
            self._log("[Lỗi] Chưa tải playit agent.", "ERR")
            return
        env    = os.environ.copy()
        secret = self.playit_secret_var.get().strip()
        if secret:
            env["SECRET_KEY"] = secret
            self._log("Chạy playit với Secret Key...", "INFO")
        else:
            self._log("Chạy playit — theo dõi Console để lấy link claim...", "INFO")
        try:
            self.playit_process = subprocess.Popen(
                [exe], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=env,
            )
        except Exception as e:
            self._log(f"[Lỗi] Không chạy được playit: {e}", "ERR")
            return

        self.root.after(0, lambda: self.btn_playit_run.configure(state="disabled"))
        self.root.after(0, lambda: self.btn_playit_stop.configure(state="normal"))

        assert self.playit_process.stdout is not None
        for line in self.playit_process.stdout:
            stripped = line.rstrip("\n")
            tag = "INFO" if "playit.gg" in stripped.lower() else ""
            self._log(f"[playit] {stripped}", tag)

        self._log("[playit đã dừng]", "WARN")
        self.root.after(0, lambda: self.btn_playit_run.configure(state="normal"))
        self.root.after(0, lambda: self.btn_playit_stop.configure(state="disabled"))

    def _on_playit_stop_clicked(self):
        if self.playit_process and self.playit_process.poll() is None:
            self.playit_process.terminate()
            self._log("Đã dừng playit.", "WARN")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    root.configure(bg=COLORS["bg"])
    try:
        if platform.system() == "Windows":
            root.iconbitmap(default="")
    except Exception:
        pass
    app = MCLauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
