#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AWA 数据管理 · 桌面启动器（网页界面，无黑窗）
=================================================
双击运行：启动本地服务 → 用「应用窗口」打开界面（无地址栏、无标签栏），
关闭窗口即自动退出服务。

为什么这样做：网页版界面最完整，改造代价最小；
用 --app 模式打开浏览器的独立窗口，用起来就像一个小程序。

参数：
    --port 8765         端口（被占用会自动换一个）
    --dir  D:\\数据      数据目录（不传则沿用上次）
    --browser chrome    指定浏览器（chrome / edge / 默认）
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

# 打包后：server.py 被 PyInstaller 收进临时目录，仍可 import
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _pick_port(prefer: int) -> int:
    """优先用指定端口，被占用则往后找。"""
    for p in [prefer] + list(range(prefer + 1, prefer + 40)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("找不到可用端口")


def _wait_ready(url: str, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.15)
    return False


# ============================================================ 浏览器 ============================================================
CHROME_PATHS = [
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Chromium\Application\chrome.exe",
]
EDGE_PATHS = [
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe",
]
# 国产 Chromium 内核浏览器也支持 --app，一并探测
OTHER_PATHS = [
    r"%LocalAppData%\360ChromeX\Chrome\Application\360ChromeX.exe",
    r"%ProgramFiles(x86)%\360\Chrome\Application\360chrome.exe",
    r"%LocalAppData%\Programs\Opera\opera.exe",
    r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"%LocalAppData%\Vivaldi\Application\vivaldi.exe",
]


def _registry_browser(name: str) -> str:
    """从注册表查默认安装路径（Windows）。"""
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    keys = {
        "chrome": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        "edge": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
    }
    k = keys.get(name)
    if not k:
        return ""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, k) as h:
                v = winreg.QueryValue(h, "")
            if v and os.path.isfile(v):
                return v
        except OSError:
            continue
    return ""


def _expand(paths):
    seen = set()
    for p in paths:
        f = os.path.expandvars(p)
        if os.path.isfile(f) and f not in seen:
            seen.add(f)
            yield f


def open_app_window(url: str, which: str = "") -> str:
    """用应用模式打开，返回浏览器名；找不到 Chromium 内核则退回默认浏览器。"""
    order = []
    if which == "chrome":
        order = ["chrome"]
    elif which == "edge":
        order = ["edge"]
    else:
        order = ["chrome", "edge"]

    # 独立 profile 目录：避免和你日常浏览器的标签混在一起
    profile = os.path.join(os.environ.get("APPDATA", HERE), "AWAHelper", "app-profile")
    os.makedirs(profile, exist_ok=True)

    for name in order:
        paths = CHROME_PATHS if name == "chrome" else EDGE_PATHS
        cands = list(_expand(paths))
        reg = _registry_browser(name)
        if reg and reg not in cands:
            cands.insert(0, reg)
        if name == "chrome":
            cands += [f for f in _expand(OTHER_PATHS) if f not in cands]
        for exe in cands:
            try:
                subprocess.Popen([
                    exe,
                    f"--app={url}",
                    f"--user-data-dir={profile}",
                    "--window-size=1440,900",
                    "--no-first-run",
                    "--no-default-browser-check",
                ], close_fds=True)
                return os.path.basename(exe)
            except OSError:
                continue

    # 兜底：系统默认浏览器（会有地址栏）
    import webbrowser
    webbrowser.open(url)
    return "默认浏览器"


# ============================================================ 主流程 ============================================================
def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="AWA 数据管理 启动器")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--dir", default="")
    ap.add_argument("--browser", default="", choices=["", "chrome", "edge"])
    ap.add_argument("--no-browser", action="store_true", help="只启动服务不开窗口")
    args = ap.parse_args()

    import server as core

    data_dir = args.dir or core.default_data_dir()
    port = _pick_port(args.port)
    url = f"http://127.0.0.1:{port}/"

    # 在本进程内跑服务（后台线程），这样关窗口能连带退出
    httpd = core.make_server(data_dir, port, open_browser=False)
    t = threading.Thread(target=httpd.serve_forever, name="awa-http", daemon=True)
    t.start()

    if not _wait_ready(url):
        # 服务没起来，留给用户一点信息（打包成无控制台时写日志文件）
        log = os.path.join(os.environ.get("APPDATA", HERE), "AWAHelper", "launch.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "w", encoding="utf-8") as f:
            f.write(f"服务启动失败：{url}\n数据目录：{data_dir}\n")
        return 1

    if args.no_browser:
        print(f"服务已启动：{url}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return 0

    # 打开窗口前刷新心跳基线与启动计时，避免"刚启动就被判定空闲"
    core.touch()

    browser = open_app_window(url, args.browser)

    # 等待窗口关闭：界面每隔几秒发心跳，超过 20 秒没心跳就退出
    core.touch_forever(httpd, url, idle_seconds=20)
    return 0


if __name__ == "__main__":
    sys.exit(main())
