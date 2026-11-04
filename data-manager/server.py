#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AWA 数据管理模块 · 本地服务（零依赖）
=================================================
只依赖 Python 标准库；导出 Excel 时若本机装了 openpyxl 则生成 .xlsx，
否则自动回退 .csv（UTF-8-BOM，Excel 可直接双击打开）。

只处理 AWA6228+ 导出的 .AWA 文本文件（GBK / TAB 分隔），WAV 不参与。

启动：
    python server.py                  # 沿用上次目录 / 自动探测含 *.AWA 的目录
    python server.py --dir D:\\data     # 指定数据目录
    python server.py --port 8765

浏览器访问： http://127.0.0.1:8765
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import report as report_core          # 报告生成内核（纯标准库）
except ImportError:                        # pragma: no cover
    report_core = None
try:                                        # Python 标准库；精简版可能被裁掉
    from tkinter import Tk, filedialog
    HAS_TK = True
except Exception:                           # noqa: BLE001
    Tk = filedialog = None
    HAS_TK = False

APP_VERSION = "3.0.0"          # 全局版本号，界面与接口共用
APP_VERSION_LABEL = "V3.0"

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")
ENV_DIR = os.environ.get("AWA_DATA_DIR", "")


def _cfg_dir() -> str:
    """配置文件目录。

    开发 / 源码运行：就放模块目录。
    PyInstaller 打包后：__file__ 指向临时解压目录（每次启动都变），
    配置写到那里会丢失，所以改放 %APPDATA%/AWAHelper。
    """
    if getattr(sys, "frozen", False):                    # 打包运行
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "AWAHelper")
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            d = os.path.expanduser("~")
        return d
    return HERE


CFG_DIR = _cfg_dir()
CONFIG_FILE = os.path.join(CFG_DIR, ".config.json")  # 记住上次 + 最近使用
MAX_RECENT = 8


# ------------------------------------------------------------ 目录配置 ---
def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            raise ValueError
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault("last", "")
    cfg.setdefault("recent", [])
    return cfg


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def remember_dir(path: str) -> dict:
    """仅记录真正读到了数据的目录；最近使用去重后置顶。"""
    cfg = load_config()
    path = os.path.abspath(path)
    cfg["last"] = path
    recent = [p for p in cfg.get("recent", []) if os.path.normcase(p) != os.path.normcase(path)]
    recent.insert(0, path)
    cfg["recent"] = recent[:MAX_RECENT]
    save_config(cfg)
    return cfg


def find_data_dirs(root: str, limit: int = 10, depth: int = 1) -> list[dict]:
    """在 root 下（depth 层）找含 *.AWA 的目录，按最后修改时间倒序。"""
    out: list[dict] = []

    def walk(base: str, level: int):
        try:
            names = sorted(os.listdir(base))
        except OSError:
            return
        for name in names:
            p = os.path.join(base, name)
            if not os.path.isdir(p) or name.startswith("."):
                continue
            try:
                files = glob.glob(os.path.join(p, "*.AWA"))
            except OSError:
                files = []
            if files:
                try:
                    newest = max(os.path.getmtime(f) for f in files)
                except OSError:
                    newest = 0
                out.append(dict(path=os.path.abspath(p), name=name, count=len(files),
                                mtime=time.strftime("%Y-%m-%d %H:%M",
                                                    time.localtime(newest))))
            elif level < depth:
                walk(p, level + 1)

    walk(root, 1)
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out[:limit]


def default_data_dir() -> str:
    """上次使用 > 环境变量 > 从程序目录往上找含 *.AWA 的目录（含下一层）。

    打包运行时程序目录=exe 所在目录；源码运行=模块上一级。
    """
    cfg_dir = load_config().get("last", "")
    for cand in (cfg_dir, ENV_DIR):
        if cand and os.path.isdir(cand):
            return os.path.abspath(cand)
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(HERE)
    for _ in range(4):                      # 逐级向上探测
        if glob.glob(os.path.join(base, "*.AWA")):
            return os.path.abspath(base)
        found = find_data_dirs(base, limit=1)
        if found:
            return found[0]["path"]
        parent = os.path.dirname(base)
        if parent == base:
            break
        base = parent
    return os.path.dirname(HERE)


def pick_folder_dialog(initial: str = "") -> str:
    """弹出系统文件夹选择框，返回所选目录；取消或环境不支持时返回空串。

    服务跑在本机，所以对话框会出现在用户桌面上。
    优先用 tkinter（Python 自带，最稳）；万一精简版 Python 没有 tkinter，
    再退回 PowerShell 的 System.Windows.Forms。
    """
    if not (initial and os.path.isdir(initial)):
        initial = os.path.expanduser("~")

    if HAS_TK:
        try:
            root = Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(parent=root, initialdir=initial,
                                           title="选择本次测试数据所在的文件夹",
                                           mustexist=True)
            root.destroy()
            return (path or "").strip()
        except Exception:
            pass

    if not sys.platform.startswith("win"):
        return ""
    return _pick_folder_via_powershell(initial)


def _pick_folder_via_powershell(initial: str) -> str:
    """兜底方案：PowerShell + System.Windows.Forms，无需额外依赖。"""
    out_file = os.path.join(HERE, ".pick.tmp")
    try:
        if os.path.exists(out_file):
            os.remove(out_file)
    except OSError:
        pass

    ps = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$d.Description = '选择本次测试数据所在的文件夹';"
        "$d.ShowNewFolderButton = $false;"
        "$d.SelectedPath = $env:AWA_INIT;"
        "$o = New-Object System.Windows.Forms.Form;"
        "$o.TopMost = $true; $o.ShowInTaskbar = $false;"
        "$o.WindowState = 'Minimized'; $o.Opacity = 0; $o.Show();"
        "$r = $d.ShowDialog($o);"
        "$o.Close(); $o.Dispose();"
        "if ($r -eq [System.Windows.Forms.DialogResult]::OK) {"
        "  $d.SelectedPath | Out-File -FilePath $env:AWA_OUT -Encoding utf8 };"
    )
    exe = (shutil.which("powershell") or shutil.which("pwsh")
           or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                           "System32", "WindowsPowerShell", "v1.0", "powershell.exe"))
    env = dict(os.environ, AWA_INIT=initial, AWA_OUT=out_file)
    try:
        subprocess.run([exe, "-NoProfile", "-STA", "-Command", ps],
                       capture_output=True, timeout=600, env=env,
                       creationflags=0x08000000)          # CREATE_NO_WINDOW
    except Exception:
        return ""
    try:
        with open(out_file, "r", encoding="utf-8-sig") as f:
            picked = f.read().strip()
        os.remove(out_file)
        return picked
    except OSError:
        return ""


ROOT_DEFAULT = default_data_dir()

BANDS_ALL = [6.3, 8, 10, 12.5, 16, 20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
             200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500,
             3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000]
METRICS = ["Leq,T", "LFmax", "LFmin", "LSmax", "LSmin"]

# 测量用途标记：OCT 主要表现噪声级，1/3OCT 主要表现隔声
TAG_NOISE = "噪声级"
TAG_INSULATION = "隔声"

# ============================================================ 编辑覆盖层 ===
# 原始 AWA 文件是仪器导出件，任何情况下都不改写。
# 界面上的修改以「文件名 → 字段路径 → 新值」的形式存进独立侧车文件，
# 读取时叠加到解析结果上；删除侧车文件即可完全还原。
EDITS_NAME = ".awa-edits.json"
EDITABLE = {
    "point": "测点名", "date": "测试日期", "time": "测试时间",
    "band": "频带值", "spl": "总值", "stat": "统计量",
}


class EditStore:
    """侧车编辑存储。按数据目录区分，不触碰 .AWA 原文件。"""

    def __init__(self, data_dir: str):
        self.dir = data_dir
        self.path = os.path.join(data_dir, EDITS_NAME)
        self.data: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and isinstance(raw.get("files"), dict):
                self.data = raw["files"]
        except (OSError, ValueError):
            self.data = {}

    def save(self) -> None:
        payload = dict(version=1,
                       updated=time.strftime("%Y-%m-%d %H:%M:%S"),
                       files=self.data)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)          # 原子替换，避免写坏

    def get(self, name: str, path: str):
        return (self.data.get(name) or {}).get(path)

    def set(self, name: str, path: str, value) -> None:
        rec = self.data.setdefault(name, {})
        if value is None or value == "":
            rec.pop(path, None)
        else:
            rec[path] = value
        if not rec:
            self.data.pop(name, None)
        self.save()

    def count(self) -> int:
        return sum(len(v) for k, v in self.data.items() if k != "_tags")

    # ---- 测量标记：噪声级 / 隔声（按组，存放在 _tags 下，不污染字段） ----
    def get_tag(self, gid: str) -> str:
        return (self.data.get("_tags") or {}).get(gid, "")

    def set_tag(self, gid: str, tag: str) -> None:
        tags = self.data.setdefault("_tags", {})
        if tag:
            tags[gid] = tag
        else:
            tags.pop(gid, None)
        if not tags:
            self.data.pop("_tags", None)
        self.save()

    def tags(self) -> dict:
        return dict(self.data.get("_tags") or {})


def band_text(hz) -> str:
    """频带显示文本：1000 -> 1k，12500 -> 12k5（与仪器导出写法一致）。"""
    hz = int(hz)
    if hz >= 1000:
        k, r = divmod(hz, 1000)
        return f"{k}k" if r == 0 else f"{k}k{r // 100}"
    return str(hz)


def _contour_at(nic, hz):
    """NIC 评价轮廓在某个频带的值（无 report 模块时返回 None）。"""
    if report_core is None or nic is None:
        return None
    try:
        return report_core.nic_contour_at(int(nic), int(hz))
    except Exception:                                  # noqa: BLE001
        return None


def band_label(key: str) -> str:
    """频带表头：1000 -> 1kHz，1250 -> 1.25kHz，12500 -> 12.5kHz，31.5 -> 31.5Hz。

    注意 1/3 倍频程里有 1.25k / 2.5k / 3.15k 这类两位数小数，
    只保留一位会错写成 1.2k / 3.1k，所以去掉多余的 0 即可，不截断。
    """
    try:
        f = float(key)
    except ValueError:
        return str(key)
    if f >= 1000:
        v = f / 1000.0
        return (f"{v:.4f}".rstrip("0").rstrip(".")) + "kHz"
    return (f"{f:.2f}".rstrip("0").rstrip(".")) + "Hz"


def norm_band(key) -> str:
    """频带键统一成「整数不带小数点」：1000.0 -> 1000，31.5 -> 31.5。

    解析、编辑、查询三处必须用同一套写法，否则会出现 1000 与 1000.0
    两个键并存，撤销时改不回来。
    """
    try:
        f = float(key)
    except (TypeError, ValueError):
        return str(key)
    return str(int(f)) if f == int(f) else str(f)


def apply_edits(rec: dict, edits: dict) -> dict:
    """把侧车编辑叠加到解析结果（深拷贝，不动缓存里的原始值）。"""
    if not edits:
        return rec
    out = dict(rec)
    out["metrics"] = {m: {norm_band(k): v for k, v in b.items()}
                      for m, b in rec.get("metrics", {}).items()}
    out["spl"] = {m: dict(v) for m, v in rec.get("spl", {}).items()}
    out["wa"] = {m: dict(v) for m, v in rec.get("wa", {}).items()}
    out["rating"] = {m: dict(v) for m, v in rec.get("rating", {}).items()}
    out["stats"] = {m: dict(v) for m, v in rec.get("stats", {}).items()}
    out["_edits"] = sorted(edits.keys())

    for path, val in edits.items():
        if path == "_tags":
            continue
        parts = path.split(":")
        try:
            if len(parts) == 1:
                out[parts[0]] = val
            elif parts[0] == "spl" and len(parts) == 3:
                out["spl"].setdefault(parts[1], {})[parts[2]] = val
            elif parts[0] == "stat" and len(parts) == 3:
                out["stats"].setdefault(parts[1], {})[parts[2]] = val
            elif parts[0] == "wa" and len(parts) == 3:
                out["wa"].setdefault(parts[1], {})[parts[2]] = val
            elif parts[0] == "rating" and len(parts) == 3:
                out["rating"].setdefault(parts[1], {})[parts[2]] = val
            elif parts[0] == "band" and len(parts) == 3:
                bands = out["metrics"].setdefault(parts[1], {})
                key = norm_band(parts[2])
                if val is None:
                    bands.pop(key, None)          # 撤销该点：回到文件原值
                else:
                    bands[key] = val
            elif parts[0] == "dist" and len(parts) == 2:
                idx = int(parts[1])
                dist = list(out.get("dist") or [])
                if 0 <= idx < len(dist):
                    dist[idx] = [dist[idx][0], val]
                    out["dist"] = dist
        except (KeyError, ValueError):
            continue
    if "Leq,T" in out["metrics"]:
        out["bands"] = out["metrics"]["Leq,T"]
    return out


# ============================================================ 文件解析 ===
def _split(line: str) -> list[str]:
    """AWA 导出为 TAB 分隔；无 TAB 时退回空白切分。"""
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    protected = re.sub(r"1/3\s+OCT", "1/3OCT", line, flags=re.IGNORECASE)
    return [c for c in re.split(r"\s+", protected.strip()) if c]


def parse_freq(label: str):
    """表头频率 -> Hz，支持 1k25Hz / 12k5Hz / 31.5Hz。"""
    s = (label or "").lower().replace("hz", "").strip()
    if not s:
        return None
    try:
        if "k" in s:
            a, _, b = s.partition("k")
            val = float(a or 0) * 1000.0
            if b:
                val += float("0." + b) * 1000.0
            return round(val, 1)
        return round(float(s), 1)
    except ValueError:
        return None


def num(cell: str):
    """'---.-' / '--' / '*' 等无效值 -> None。"""
    if cell is None:
        return None
    s = str(cell).strip()
    if not s or set(s) <= {"-", ".", "*"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_awa(path: str) -> dict:
    """解析一份 AWA 文件（GBK / TAB 分隔）。返回 JSON 友好结构。"""
    with open(path, "rb") as f:
        raw = f.read().decode("gbk", errors="ignore")
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    name = os.path.basename(path)
    rec = dict(file=name, kind="?", point="", date="", time="", ts="", mode="",
               bands={}, metrics={}, spl={}, wa={}, rating={}, stats={},
               dist=[], rows=0,
               model="", serial="", range_="", weight="", calibrate="")
    rec["rows"] = len([x for x in lines if x.strip()])

    # 文件头三行：型号 / 量程 / 校准
    for ln in lines[:3]:
        if ln.startswith("Model:"):
            parts = dict(p.split(":", 1) for p in ln.replace("\t", " ").split() if ":" in p)
            rec["model"] = parts.get("Model", "").strip()
            rec["serial"] = parts.get("Serial", "").strip()
        elif ln.startswith("R:"):
            rec["range_"] = ln.split("\t")[0].replace("R:", "").strip()
            m = re.search(r"Wei:(\S+)", ln)
            if m:
                rec["weight"] = m.group(1)
        elif ln.startswith("Calibrate@"):
            rec["calibrate"] = ln.replace("Calibrate@", "").strip()

    # 定位表头
    hidx = None
    for i, ln in enumerate(lines):
        if "测点名" in ln:
            hidx = i
            break

    # NUM（声级分布）：无表头，两列「声级 / 百分比」
    if hidx is None:
        rec["kind"] = "NUM"
        for ln in lines:
            cols = _split(ln)
            if len(cols) >= 2:
                a, b = num(cols[0]), num(cols[1])
                if a is not None and b is not None:
                    rec["dist"].append([a, b])
        rec["dist"].sort(key=lambda x: x[0])
        return rec

    headers = _split(lines[hidx])
    while headers and headers[-1] == "":
        headers.pop()

    def col_index(*keys):
        for k in keys:
            for j, h in enumerate(headers):
                if h == k:
                    return j
        return -1

    i_point = col_index("测点名")
    i_date = col_index("测试日期")
    i_time = col_index("测试时间")
    i_mode = col_index("方式")
    i_ts = col_index("经历时间")
    i_metric = col_index("指标", "统计参量")

    freq_cols = {}
    for j, h in enumerate(headers):
        f = parse_freq(h)
        if f and f in BANDS_ALL:
            freq_cols[j] = f

    spl_cols = {}
    for j, h in enumerate(headers):
        h2 = h.upper().replace(" ", "")
        if h2.startswith("SPL(") and h2.endswith(")"):
            spl_cols[j] = ("A", h2[4:-1])          # SPL(A) 计权声级
        elif h2.startswith("W_") and len(h2) == 3:
            spl_cols[j] = ("WA", h2[2:])           # W_A / W_C / W_Z 计权总值
        elif h2 in ("NR", "NC", "RC", "W_NR", "W_NC"):
            key = h2.replace("W_", "")
            spl_cols[j] = ("RATING", key)          # NR / NC 评价数

    boundary = max(i_point, i_metric, i_ts, i_date, i_time, i_mode)
    stat_cols = {}
    for j, h in enumerate(headers):
        if j in freq_cols or j in spl_cols or j <= boundary:
            continue
        if h:
            stat_cols[j] = h

    data_rows = []
    for ln in lines[hidx + 1:]:
        if not ln.strip():
            continue
        cols = _split(ln)
        if len(cols) >= 2:
            data_rows.append(cols)
    if not data_rows:
        return rec

    first = data_rows[0]

    def cell(row, idx):
        return row[idx].strip() if 0 <= idx < len(row) else ""

    rec["point"] = cell(first, i_point)
    rec["date"] = cell(first, i_date)
    rec["time"] = cell(first, i_time)
    rec["ts"] = cell(first, i_ts)
    mode = cell(first, i_mode).upper()
    rec["mode"] = cell(first, i_mode)
    if "1/3" in mode:
        rec["kind"] = "1/3OCT"
    elif mode == "OCT" or (freq_cols and len(freq_cols) <= 12):
        rec["kind"] = "OCT"
    elif mode == "STA":
        rec["kind"] = "STA"
    else:
        rec["kind"] = "STA" if not freq_cols else "OCT"

    for cols in data_rows:
        metric = cell(cols, i_metric)
        if not metric:
            continue
        bands = {}
        for j, f in freq_cols.items():
            if j < len(cols):
                v = num(cols[j])
                if v is not None:
                    bands[norm_band(f)] = v
        spl, wa, rating = {}, {}, {}
        for j, (grp, k) in spl_cols.items():
            if j >= len(cols):
                continue
            v = num(cols[j])
            if v is None:
                continue
            if grp == "A":
                spl[k] = v                       # SPL(A/C/Z/U/T/B)
            elif grp == "WA":
                wa[k] = v                        # W_A / W_C / W_Z
            else:
                rating[k] = v                    # NR / NC
        stats = {}
        for j, nm in stat_cols.items():
            if j < len(cols):
                v = num(cols[j])
                if v is not None:
                    stats[nm] = v
        if bands:
            rec["metrics"][metric] = bands
        if spl:
            rec["spl"][metric] = spl
        if wa:
            rec["wa"][metric] = wa
        if rating:
            rec["rating"][metric] = rating
        if stats:
            rec["stats"][metric] = stats

    rec["bands"] = rec["metrics"].get("Leq,T", {})
    # 记录字段位置（解析期的行列号），仅用于界面定位，不回写原文件
    rec["_row"] = hidx + 2                      # 人看行号：表头是第 hidx+1 行
    rec["_cols"] = dict(
        bands={norm_band(f): j for j, f in freq_cols.items()},
        spl={f"{g}:{k}": j for j, (g, k) in spl_cols.items()},
        stats={nm: j for j, nm in stat_cols.items()},
        point=i_point, date=i_date, time=i_time,
    )
    return rec


# ============================================================ 数据仓库 ===
CATEGORIES = [
    ("13OCT", "1/3 OCT数据"),
    ("OCT", "OCT数据"),
    ("STA", "统计汇总数据"),
    ("FFT", "FFT数据"),
    ("TOTAL", "总值数据"),
    ("EXPOSE", "声暴露计数据"),
    ("H24", "24H小时数据"),
    ("FIX", "定量噪声数据"),
    ("13OCT_INST", "1/3OCT瞬时数据"),
    ("11OCT_INST", "1/1OCT瞬时数据"),
    ("TOTAL_INST", "总值瞬时数据"),
    ("STA_INST", "统计瞬时数据"),
]


class Store:
    def __init__(self, root: str):
        self.dir = os.path.abspath(root)
        self.records: dict[str, dict] = {}
        self.elapsed_ms = 0.0
        self.scanned_at = 0.0
        self.errors: list[str] = []
        self.edits = EditStore(self.dir)

    # ---------------- 扫描 ----------------
    def scan(self, new_dir: str | None = None) -> dict:
        if new_dir:
            d = os.path.abspath(os.path.expanduser(new_dir))
            if not os.path.isdir(d):
                raise ValueError(f"目录不存在：{d}")
            self.dir = d

        t0 = time.perf_counter()
        records, errors = {}, []
        try:
            names = sorted(os.listdir(self.dir))
        except OSError as e:
            raise ValueError(f"无法读取目录：{e}")

        for name in names:
            path = os.path.join(self.dir, name)
            if not os.path.isfile(path):
                continue
            if os.path.splitext(name)[1].lower() != ".awa":
                continue                                    # 只处理 AWA，WAV 不参与
            try:
                records[name] = parse_awa(path)
            except Exception as e:                          # 单文件失败不影响整体
                errors.append(f"{name}：{e}")
                records[name] = dict(file=name, kind="ERR", point="", date="",
                                     time="", ts="", mode="", bands={},
                                     metrics={}, spl={}, wa={}, rating={},
                                     stats={}, dist=[],
                                     rows=0, error=str(e))
        self.records, self.errors = records, errors
        self.edits = EditStore(self.dir)             # 每个数据目录各自的侧车
        self.elapsed_ms = (time.perf_counter() - t0) * 1000
        self.scanned_at = time.time()

        cfg = remember_dir(self.dir) if records else load_config()
        # 没读到数据时，给出邻近可用目录，省得用户手动翻
        suggest = [] if records else (find_data_dirs(self.dir) or
                                      find_data_dirs(os.path.dirname(self.dir)))
        return dict(dir=self.dir, elapsedMs=round(self.elapsed_ms, 1),
                    files=len(records), errors=errors,
                    recent=cfg.get("recent", []), suggest=suggest,
                    instrument=self._instrument())

    def _instrument(self) -> dict:
        for r in self.records.values():
            if r.get("model"):
                return dict(model=r["model"], serial=r.get("serial", ""),
                            range=r.get("range_", ""), weight=r.get("weight", ""),
                            calibrate=r.get("calibrate", ""))
        return {}

    def ensure(self):
        """未扫描过则先扫描一次（避免直接调 /api/table 时空白）。"""
        if not self.scanned_at:
            self.scan()

    # ---------------- 分类计数 ----------------
    def counts(self) -> dict:
        c = defaultdict(int)
        for r in self.records.values():
            k = r["kind"]
            c["13OCT" if k == "1/3OCT" else k] += 1
        c["TOTAL"] = sum(len(r["spl"]) for r in self.records.values())
        for key in ("FFT", "EXPOSE", "H24", "FIX",
                    "13OCT_INST", "11OCT_INST", "TOTAL_INST", "STA_INST"):
            c.setdefault(key, 0)
        return dict(c)

    def categories(self) -> list[dict]:
        c = self.counts()
        return [dict(key=k, label=lab, count=c.get(k, 0)) for k, lab in CATEGORIES]

    # ---------------- 表格 ----------------
    @staticmethod
    def _f(v, spec="{:.1f}", dash="—"):
        return dash if v is None else spec.format(v)

    def _view(self, r: dict, organize: bool = True) -> dict:
        """取一条记录的展示值。

        原始数据是仪器导出的备份，不参与任何整理，必须看到真值；
        只有整理视图才叠加侧车里的改动。
        """
        if not organize:
            return r
        return apply_edits(r, self.edits.data.get(r["file"], {}))

    # 原始视图显示全部频带；整理视图按现场习惯只留关注区间
    VIEW_BANDS = {
        "13OCT": {"lo": 100, "hi": 5000},      # 1/3OCT: 100Hz ~ 5kHz
        "OCT": {"lo": 63, "hi": 8000},         # OCT: 63Hz ~ 8kHz
    }

    def _spectrum_table(self, cat: str, organize: bool,
                        tag_filter: str = "") -> dict:
        """1/3OCT 与 OCT 的表格。

        organize=True 为数据整理视图，按现场汇报口径精简：
          1/3OCT → SPL(A) + 100Hz~5kHz 频带
          OCT    → SPL(A) + 63Hz~8kHz 频带 + W_A + NR + NC
        organize=False 为原始数据视图，完整展示所有频带与全部总值列。
        """
        kind = "1/3OCT" if cat == "13OCT" else "OCT"
        files = [r for r in self._sorted() if r["kind"] == kind]
        if tag_filter:
            files = [r for r in files
                     if self.edits.get_tag(self.group_of(r["file"])) == tag_filter]
        win = self.VIEW_BANDS.get(cat, {}) if organize else {}

        # 这一类文件用的是 SPL(x) 还是 W_x？决定取值与编辑路径
        spl_keys = set()
        for r in files:
            for m in r.get("spl", {}).values():
                spl_keys.update(m.keys())

        # ---- 频带列 ----
        all_bands = sorted(
            {norm_band(b) for r in files for b in r["metrics"].get("Leq,T", {})},
            key=float)
        if win:
            band_list = [b for b in all_bands
                         if win["lo"] <= float(b) <= win["hi"]]
        else:
            band_list = all_bands

        # ---- 表头 ----
        # 列序：经历时间在测试时间之前；测试时间为仪器记录，整理中只读
        headers = [("序号", 58), ("文件名", 150), ("测点名", 124), ("测试日期", 104),
                   ("经历时间", 96), ("测试时间", 92)]
        if organize:
            headers.append(("标记", 84))
        tail = []                       # [(表头, 宽度, 取值函数, 编辑路径)]
        item_pos = {}                   # tail 下标 -> (row 列号, 编辑路径)
        f = self._f

        def add_spl(key, label, width=70):
            # OCT 文件没有 SPL(x) 列，只有 W_x，取值时依次回退
            def get(v, k=key):
                spl = v["spl"].get("Leq,T", {})
                if k in spl:
                    return f(spl[k])
                return f(v["wa"].get("Leq,T", {}).get(k))
            path = ("spl" if key in spl_keys else "wa") + f":Leq,T:{key}"
            tail.append((label, width, get, path))

        if organize and cat == "13OCT":
            add_spl("A", "SPL(A)", 74)
        elif organize:                                   # OCT
            add_spl("A", "SPL(A)", 70)
        else:                                            # 原始视图：完整
            for k, lbl in (("A", "SPL(A)"), ("C", "SPL(C)"), ("Z", "SPL(Z)"),
                           ("U", "SPL(U)"), ("T", "SPL(T)"), ("B", "SPL(B)")):
                add_spl(k, lbl, 68)
            tail.append(("Leq,T (A)", 78,
                         lambda v: f(v["spl"].get("Leq,T", {}).get("A")),
                         "spl:Leq,T:A"))

        # 先把 tail 中已有的列（SPL 等）并入表头，再确定频带起始列
        for item in tail:
            headers.append((item[0], item[1]))
        band_start = len(headers)
        for b in band_list:
            headers.append((band_label(b), 66))
            tail.append((band_label(b), 66,
                         lambda v, bb=b: f(v["metrics"].get("Leq,T", {}).get(bb)),
                         f"band:Leq,T:{b}"))

        # 末尾补 W_A / NR / NC：原始视图总是全给，整理视图仅 OCT 需要
        extra_start = band_start + len(band_list)
        # 1/3OCT 文件本身不含 W_x / NR / NC 列，只有 OCT 文件有
        has_wa = cat == "OCT"
        if has_wa:
            wa_keys = [("A", "W_A")] if organize else [("A", "W_A"), ("C", "W_C"), ("Z", "W_Z")]
            for wk, wlbl in wa_keys:
                headers.append((wlbl, 62))
                tail.append((wlbl, 62,
                             lambda v, k=wk: f(v["wa"].get("Leq,T", {}).get(k)),
                             f"wa:Leq,T:{wk}"))
            for k in ("NR", "NC"):
                headers.append((k, 56))
                tail.append((k, 56,
                             lambda v, kk=k: f(v["rating"].get("Leq,T", {}).get(kk)),
                             f"rating:Leq,T:{k}"))

        # 登记每一列在 row 中的真实位置（基础列 6 个 + 整理视图的标记列 + tail 顺序）
        base_cols = 6 + (1 if organize else 0)
        for j, item in enumerate(tail):
            item_pos[j] = (base_cols + j, item[3])

        # ---- 数据行 ----
        rows, fields = [], []
        for i, r in enumerate(files, 1):
            v = self._view(r, organize)
            row = [str(i), r["file"], v["point"], v["date"], v["ts"], v["time"]]
            if organize:
                # 标记属于整理结果，原始数据视图不展示
                row.append(self.edits.get_tag(self.group_of(r["file"])))
            row += [item[2](v) for item in tail]
            rows.append(row)

            cells = {2: dict(p="point", t="text", one="group"),
                     3: dict(p="date", t="text", one="group"),
                     4: dict(p="ts", t="text"),          # 经历时间可改
                     5: dict(ro=1),                       # 测试时间只读
                     6: dict(p="_tag", t="tag")}          # 噪声级 / 隔声
            for j in range(len(tail)):
                col, path = item_pos[j]
                cells[col] = dict(p=path, t="num")
            fields.append(cells)

        scope = (f"{band_label(win['lo'])}~{band_label(win['hi'])}"
                 if win else f"全部 {len(band_list)} 个频带")
        note = f"共 {len(files)} 份 {kind} 文件；{'整理视图' if organize else '原始视图'}，{scope}"
        return dict(headers=headers, rows=rows, fields=fields, kind="spectrum",
                    bandCols=band_list, bandStart=band_start,
                    extraStart=extra_start, note=note)

    def table(self, cat: str, organize: bool = False,
              tag_filter: str = "") -> dict:
        """返回表头、行数据与「可编辑单元格」映射。

        fields[i][j] 描述第 i 行第 j 列能否编辑及其字段路径：
            {"p": "point"}              测点名
            {"p": "spl:Leq,T:A"}        总值  A/C/Z/U/T/B
            {"p": "stat:LeqT:Lmax"}     STA 统计量
            {"p": "band:Leq,T:1000"}    频带值（曲线点）
        """
        self.ensure()
        if cat in ("13OCT", "OCT"):
            return self._spectrum_table(cat, organize, tag_filter)

        if cat == "STA":
            files = [r for r in self._sorted() if r["kind"] == "STA"]
            keys = ("LeqT", "Lmax", "Lmin", "L10", "L50", "L90", "L95", "SD", "SEL")
            headers = [("序号", 58), ("文件名", 150), ("测点名", 124), ("测试日期", 104),
                       ("测试时间", 92), ("LeqT", 64), ("Lmax", 64), ("Lmin", 64),
                       ("L10", 60), ("L50", 60), ("L90", 60), ("L95", 60),
                       ("SD", 56), ("SEL", 64)]
            rows, fields = [], []
            for i, r in enumerate(files, 1):
                v = self._view(r, organize)
                metric, st = next(iter(v["stats"].items()), ("A F", {}))
                rows.append([str(i), r["file"], v["point"], v["date"], v["time"]] +
                            [self._f(st.get(k)) for k in keys])
                cells = {2: dict(p="point", t="text", one="group"),
                         3: dict(p="date", t="text", one="group"),
                         4: dict(p="time", t="text", one="group")}
                for col, k in enumerate(keys, 5):
                    cells[col] = dict(p=f"stat:{metric}:{k}", t="num")
                fields.append(cells)
            return dict(headers=headers, rows=rows, fields=fields, kind="stats",
                        note=f"共 {len(files)} 份 STA 统计文件")

        if cat == "TOTAL":
            headers = [("序号", 58), ("文件名", 150), ("测点名", 124), ("测试日期", 104),
                       ("指标", 82), ("SPL(A)", 68), ("SPL(C)", 68), ("SPL(Z)", 68),
                       ("SPL(U)", 68), ("SPL(T)", 68), ("SPL(B)", 68)]
            rows, fields = [], []
            n = 0
            for r in self._sorted():
                if not r["spl"]:
                    continue
                v = self._view(r, organize)
                for metric in METRICS:
                    if metric not in v["spl"]:
                        continue
                    spl = v["spl"][metric]
                    n += 1
                    rows.append([str(n), r["file"], v["point"], v["date"], metric] +
                                [self._f(spl.get(k)) for k in
                                 ("A", "C", "Z", "U", "T", "B")])
                    cells = {2: dict(p="point", t="text", one="group"),
                             3: dict(p="date", t="text", one="group")}
                    for col, k in enumerate(("A", "C", "Z", "U", "T", "B"), 5):
                        cells[col] = dict(p=f"spl:{metric}:{k}", t="num")
                    fields.append(cells)
            return dict(headers=headers, rows=rows, fields=fields, kind="total",
                        note=f"从 {sum(1 for r in self.records.values() if r['spl'])} "
                             f"份频谱文件中提取 {n} 条总值记录")

        if cat == "NUM":
            files = [r for r in self._sorted() if r["kind"] == "NUM"]
            headers = [("序号", 58), ("文件名", 150), ("测点名", 124), ("测试日期", 104),
                       ("声级范围 (dB)", 128), ("峰值档位 (dB)", 104),
                       ("最大占比 (%)", 104), ("分布档数", 84)]
            rows, fields = [], []
            for i, r in enumerate(files, 1):
                v = self._view(r, organize)
                d = v["dist"]
                meta = self._sibling(r["file"]) or {}
                point = v["point"] or meta.get("point", "")
                date = v["date"] or meta.get("date", "")
                # NUM 文件本身无表头，测点名/日期取自同编号的频谱文件；
                # 修改会同步写回该组全部文件，所以这里也可编辑
                if d:
                    lo, hi = d[0][0], d[-1][0]
                    pk = max(d, key=lambda x: x[1])
                    rows.append([str(i), r["file"], point, date,
                                 f"{lo:.0f} ~ {hi:.0f}", f"{pk[0]:.0f}",
                                 f"{pk[1]:.2f}", str(len(d))])
                else:
                    rows.append([str(i), r["file"], point, date,
                                 "—", "—", "—", "0"])
                fields.append({2: dict(p="point", t="text"),
                               3: dict(p="date", t="text", one="group")})
            return dict(headers=headers, rows=rows, fields=fields, kind="num",
                        note=f"共 {len(files)} 份声级分布文件")

        return dict(headers=[("序号", 52), ("文件名", 128)], rows=[], fields=[],
                    kind="empty",
                    note="该类数据本次未读取到（AWA6228+ 未导出该类型，或本批次未测量）")

    def _sibling(self, name: str) -> dict | None:
        """NUM_xxxx 无表头信息，用同编号的 1_3_/OCT 文件补测点与日期。"""
        m = re.search(r"(\d+)\D*$", os.path.splitext(name)[0])
        if not m:
            return None
        no = m.group(1)
        for cand in (f"1_3_{no}.AWA", f"OCT_{no}.AWA", f"STA_{no}.AWA"):
            r = self.records.get(cand)
            if r and r.get("point"):
                return r
        return None

    def _sorted(self) -> list[dict]:
        def key(r):
            m = re.search(r"(\d+)\s*$", os.path.splitext(r["file"])[0])
            return (r["kind"], int(m.group(1)) if m else 10 ** 9, r["file"])
        return sorted(self.records.values(), key=key)

    # ---------------- 详情 ----------------
    def detail(self, name: str, organize: bool = True) -> dict | None:
        r = self.records.get(name)
        if r is None:
            return None
        out = self._view(r, organize)
        out["file"] = name
        # 只保留有效频带，前端按数值排序
        for m, bands in out["metrics"].items():
            out["metrics"][m] = {k: v for k, v in bands.items()
                                 if float(k) in BANDS_ALL}
        # 曲线点是否可编辑：给出每个频带的字段路径
        out["editPaths"] = {
            m: {b: f"band:{m}:{b}" for b in out["metrics"].get(m, {})}
            for m in METRICS if m in out["metrics"]
        }
        if out["kind"] == "NUM":
            out["editPaths"] = {"dist": {str(i): f"dist:{i}"
                                         for i in range(len(out.get("dist") or []))}}
        return out

    # ---------------- 编辑 ----------------
    # ---------------- 测量组（同编号的 1_3_/OCT_/STA_/NUM_） ----------------
    @staticmethod
    def group_of(name: str) -> str:
        """取文件名的测量编号：1_3_0001 / OCT_0001 / STA_0001 -> '0001'。

        同一编号的四类文件是同一次测量的不同导出视图，
        测点名/日期/时间这类元数据必须一起改，否则表格里会对不上。
        """
        stem = os.path.splitext(name)[0]
        m = re.search(r"(\d+)\D*$", stem)
        return m.group(1) if m else stem

    def group_members(self, name: str) -> list[str]:
        """同组中确实存在的文件，频谱优先（把用户的修改值当权威）。"""
        gid = self.group_of(name)
        order = {"1/3OCT": 0, "OCT": 1, "STA": 2, "NUM": 3}
        members = [n for n in self.records if self.group_of(n) == gid
                   and self.records[n].get("kind") in order]
        members.sort(key=lambda n: (order.get(self.records[n]["kind"], 9), n))
        return members

    def update(self, name: str, path: str, value: str,
               group: bool = True) -> dict:
        """记录一条修改到侧车文件；.AWA 原文件保持只读。

        group=True 时，元数据（测点名/日期/时间）会同步到同组所有文件，
        声级数值（spl/stat/band/dist）只属于当前文件，不联动。
        """
        self.ensure()                       # 直接调接口时也能用
        if name not in self.records:
            raise ValueError(f"未找到文件：{name}")

        # 测量标记：按组存，不属于任何单个文件字段
        if path == "_tag":
            tag = (value or "").strip()
            if tag not in ("", TAG_NOISE, TAG_INSULATION):
                raise ValueError(f"未知标记：{tag}")
            gid = self.group_of(name)
            self.edits.set_tag(gid, tag)
            return dict(file=name, path=path, value=tag, groupId=gid,
                        targets=[n for n in self.records
                                 if self.group_of(n) == gid],
                        edits=self.edits.count())

        head = path.split(":")[0]
        if head not in ("point", "date", "time", "ts", "spl", "stat", "band",
                        "dist", "wa", "rating"):
            raise ValueError(f"该字段不支持编辑：{path}")

        if head in ("point", "date", "time", "ts"):
            val = None if value in (None, "") else str(value).strip()
            targets = self.group_members(name) if group else [name]
        else:
            if value in (None, ""):
                val = None
            else:
                try:
                    val = round(float(str(value).strip()), 3)
                except ValueError:
                    raise ValueError(f"请输入数字：{value}") from None
            targets = [name]

        for t in targets:
            self.edits.set(t, path, val)
        return dict(file=name, path=path, value=val,
                    targets=targets, groupId=self.group_of(name),
                    edits=self.edits.count())

    def revert(self, name: str | None = None) -> int:
        """撤销：指定文件则该文件全部还原，否则清空本目录所有编辑。"""
        if name:
            self.edits.data.pop(name, None)
            n = 1
        else:
            n = len(self.edits.data)
            self.edits.data = {}
        self.edits.save()
        return n

    # ---------------- 批量整理 ----------------
    def batch_update(self, files: list[str], path: str, value,
                     group: bool = True) -> dict:
        """一次给多个文件写同一个字段值。

        - point 支持模板：'{gid}' 替换为测量编号，'{i}' 为序号，
          例如 '会议室-{i}' → 会议室-01、会议室-02 ……
        - group=True 时元数据仍会扩散到同组全部文件（去重后统一处理）
        """
        head = path.split(":")[0]
        if head not in ("point", "date", "time"):
            raise ValueError("批量整理只支持测点名、测试日期、测试时间")

        targets: list[str] = []
        for name in files:
            if name not in self.records:
                continue
            members = self.group_members(name) if group else [name]
            for m in members:
                if m not in targets:
                    targets.append(m)
        if not targets:
            raise ValueError("没有可处理的文件")

        written = 0
        # {i} 按「测量组」编号，而不是按文件，否则同组四个文件会拿到不同序号
        seen_group: dict[str, int] = {}
        for t in targets:
            gid = self.group_of(t)
            if gid not in seen_group:
                seen_group[gid] = len(seen_group) + 1
            raw = value
            if head == "point" and isinstance(raw, str):
                raw = (raw.replace("{gid}", gid)
                          .replace("{i}", str(seen_group[gid]))
                          .replace("{n}", str(len(seen_group))))
            if raw in (None, ""):
                val = None
            else:
                val = str(raw).strip()
            self.edits.set(t, path, val)
            written += 1

        return dict(path=path, written=written, targets=targets,
                    groups=len(seen_group), edits=self.edits.count())

    def groups(self) -> list[dict]:
        """按测量编号聚合：一组 = 一次测量的四类导出。"""
        buckets: dict[str, list[str]] = {}
        for name in self.records:
            buckets.setdefault(self.group_of(name), []).append(name)

        out = []
        for gid, names in buckets.items():
            names.sort()
            base = self.records.get(f"1_3_{gid}.AWA") or self.records[names[0]]
            v = self._view(base)
            spl = v.get("spl", {}).get("Leq,T", {})
            out.append(dict(
                gid=gid,
                point=v.get("point", ""),
                date=v.get("date", ""),
                time=v.get("time", ""),
                splA=spl.get("A"),
                splZ=spl.get("Z"),
                files=names,
                kinds=sorted({self.records[n]["kind"] for n in names}),
                edited=any(n in self.edits.data for n in names),
                ts=v.get("ts", ""),
            ))
        out.sort(key=lambda g: (g["date"] or "", g["time"] or "", g["gid"]))
        return out

    def tag_counts(self, cat: str) -> dict:
        """当前分类下，各标记的组数（供界面显示筛选结果数量）。"""
        kind = {"13OCT": "1/3OCT", "OCT": "OCT"}.get(cat)
        if not kind:
            return {}
        gids = {self.group_of(r["file"]) for r in self.records.values()
                if r["kind"] == kind}
        out = {TAG_NOISE: 0, TAG_INSULATION: 0, "未标记": 0}
        for g in gids:
            t = self.edits.get_tag(g)
            out[t if t else "未标记"] = out.get(t if t else "未标记", 0) + 1
        return out

    def summary(self) -> dict:
        """整理概览：测点数量、重复点名、未命名等。"""
        gs = self.groups()
        points = [g["point"] for g in gs if g["point"]]
        counter = defaultdict(int)
        for p in points:
            counter[p] += 1
        dup = {p: c for p, c in counter.items() if c > 1}
        unnamed = [g["gid"] for g in gs if not g["point"] or g["point"].startswith("DATA_")]
        return dict(groups=len(gs), named=len(points) - len(unnamed),
                    unnamed=len(unnamed), uniqPoints=len(counter),
                    duplicates=len(dup), dupDetail=dup,
                    files=len(self.records), edited=self.edits.count())


# ============================================================ 导出 ===
def build_export(cat: str, store: Store, keep: list[list[str]] | None = None,
                 organize: bool = False):
    """keep 不为 None 时只导出这些行（按文件名集合过滤，供整理模块按条件导出）。"""
    data = store.table(cat, organize=organize)
    if keep is not None:
        wanted = {r[1] for r in keep} if keep and isinstance(keep[0], list) else set(keep)
        data["rows"] = [r for r in data["rows"] if r[1] in wanted]
    headers = [h[0] for h in data["headers"]]
    label = dict(CATEGORIES).get(cat, cat)
    # Excel 工作表名 / 文件名不允许出现 / \ : * ? [ ]
    safe = re.sub(r'[\\/:*?\[\]]', "-", label)
    stamp = time.strftime("%Y%m%d_%H%M")

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = safe[:28]
        head_fill = PatternFill("solid", fgColor="1F4E79")
        thin = Side(style="thin", color="D8DEE6")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        for j, h in enumerate(headers, 1):
            c = ws.cell(row=1, column=j, value=h)
            c.fill = head_fill
            c.font = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = border
        for i, row in enumerate(data["rows"], 2):
            for j, v in enumerate(row, 1):
                c = ws.cell(row=i, column=j, value=v)
                c.font = Font(name="微软雅黑", size=9)
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = border
                if isinstance(v, str):
                    try:
                        c.value = float(v)
                        c.number_format = "0.0"
                    except ValueError:
                        pass
        for j, w in enumerate([h[1] for h in data["headers"]], 1):
            ws.column_dimensions[get_column_letter(j)].width = max(8, w / 8.2)
        ws.freeze_panes = "A2"
        ws.row_dimensions[1].height = 26
        bio = io.BytesIO()
        wb.save(bio)
        return bio.getvalue(), f"AWA_{safe}_{stamp}.xlsx", \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    except Exception:
        import csv
        bio = io.StringIO()
        w = csv.writer(bio, lineterminator="\r\n")
        w.writerow(headers)
        w.writerows(data["rows"])
        return bio.getvalue().encode("utf-8-sig"), f"AWA_{safe}_{stamp}.csv", \
            "text/csv; charset=utf-8"


# ============================================================ HTTP 服务 ===
class Handler(BaseHTTPRequestHandler):
    server_version = "AWADataManager/3.0"
    protocol_version = "HTTP/1.1"
    store: Store = None                                     # type: ignore

    # ---- 工具 ----
    def log_message(self, fmt, *args):                      # 静默，避免刷屏
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code: int = 200):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", code)

    # ---- 路由 ----
    def do_POST(self):
        """只接收 JSON 小请求：字段编辑 / 撤销编辑。"""
        u = urllib.parse.urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except (ValueError, UnicodeDecodeError):
            return self._json(dict(ok=False, error="请求体不是合法 JSON"), 400)

        try:
            if u.path == "/api/edit":
                res = self.store.update(body.get("file", ""),
                                        body.get("path", ""),
                                        body.get("value"))
                return self._json(dict(ok=True, **res))

            if u.path == "/api/report/plan":
                # 保存整份清单
                if report_core is None:
                    return self._json(dict(ok=False, error="缺少 report.py"), 500)
                self.store.ensure()
                raw = body.get("items") or []
                items = [report_core.Item.from_dict(d) for d in raw]
                report_core.save_plan(self.store.dir, items)
                return self._json(dict(ok=True, count=len(items)))

            if u.path == "/api/report/export":
                if report_core is None:
                    return self._json(dict(ok=False, error="缺少 report.py"), 500)
                self.store.ensure()
                res = self._export_report(body)
                return self._json(dict(ok=True, **res))

            if u.path == "/api/batch":
                res = self.store.batch_update(
                    files=body.get("files") or [],
                    path=body.get("path", ""),
                    value=body.get("value"),
                    group=bool(body.get("group", True)))
                return self._json(dict(ok=True, **res))

            if u.path == "/api/revert":
                n = self.store.revert(body.get("file") or None)
                return self._json(dict(ok=True, reverted=n,
                                       count=self.store.edits.count()))

            return self._json(dict(ok=False, error="not found"), 404)
        except ValueError as e:
            return self._json(dict(ok=False, error=str(e)), 400)
        except Exception as e:                              # noqa: BLE001
            return self._json(dict(ok=False, error=f"{type(e).__name__}: {e}"), 500)

    # ---------------- 报告：导出 ----------------
    def _export_report(self, body: dict) -> dict:
        """生成 xlsx（含曲线图）。返回文件列表供前端下载。"""
        items = [report_core.Item.from_dict(d) for d in (body.get("items") or [])]
        if not items:
            items = report_core.load_plan(self.store.dir)
        if not items:
            raise ValueError("清单是空的，先添加测点")
        meta = body.get("meta") or {}
        results = report_core.compute_all(self.store, items)

        out_dir = os.path.join(self.store.dir, "报告输出")
        os.makedirs(out_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M")
        name = (meta.get("project") or "报告").strip() or "报告"
        safe = re.sub(r'[\\/:*?"<>|]', "-", name)
        xlsx = os.path.join(out_dir, f"{safe}_{stamp}.xlsx")
        report_core.write_xlsx(results, xlsx, meta=meta)

        # 同时导出可下载副本的 URL 列表
        rel = os.path.relpath(xlsx, self.store.dir).replace(os.sep, "/")
        return dict(path=xlsx, name=os.path.basename(xlsx),
                    url="/api/report/file?p=" + urllib.parse.quote(rel),
                    rows=len(results),
                    okCount=sum(1 for r in results if r.ok))

    # ---------------- 报告：行数据与明细 ----------------
    @staticmethod
    def _report_row(item, r) -> dict:
        """表格一行：清单字段 + 计算结果。"""
        d = item.to_dict()
        d.update(
            value=r.value or "",
            value_num=r.value_num,
            nc=r.nc,
            nic=r.nic,
            ok=r.ok,
            error=r.error,
            passFlag=("" if r.pass_ is None else ("满足" if r.pass_ else "不满足")),
            designNum=r.design_num,
            # 交叉表要按频带取值：噪声级 8 个倍频程、隔声 18 个 1/3 倍频程
            bands=[None if v is None else round(v, 1) for v in (r.bands or [])],
        )
        return d

    @staticmethod
    def _report_detail(r) -> dict:
        """右侧预览：频带表 + 曲线数据。"""
        bands = []
        if r.item.kind == "噪声级":
            labels = [63, 125, 250, 500, 1000, 2000, 4000, 8000]
            for hz, v in zip(labels, r.bands or []):
                bands.append(dict(hz=hz, label=band_text(hz), value=v,
                                  contour=None, deficit=None))
        else:
            hzs = [100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000,
                   1250, 1600, 2000, 2500, 3150, 4000, 5000]
            for i, hz in enumerate(hzs):
                bands.append(dict(
                    hz=hz, label=band_text(hz),
                    value=(r.bands[i] if i < len(r.bands) else None),
                    contour=_contour_at(r.nic, hz),
                    deficit=(r.deficit[i] if i < len(r.deficit) else None)))
        return dict(
            kind=r.item.kind, item=r.item.to_dict(),
            dataOk=r.ok, error=r.error,
            value=r.value, nc=r.nc, nic=r.nic,
            nrInstrument=r.nr_instrument,
            passFlag=("" if r.pass_ is None else ("满足" if r.pass_ else "不满足")),
            bands=bands,
        )

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        path = u.path

        try:
            if path == "/api/report/file":
                # 下载报告输出目录里的文件（限制在 报告输出/ 下，防越界）
                rel = q.get("p", "")
                base = os.path.abspath(os.path.join(self.store.dir, "报告输出"))
                full = os.path.abspath(os.path.join(self.store.dir, rel))
                if not full.startswith(base) or not os.path.isfile(full):
                    raise ValueError("文件不存在")
                with open(full, "rb") as f:
                    data = f.read()
                ctype = ("application/vnd.openxmlformats-officedocument."
                         "spreadsheetml.sheet" if full.endswith(".xlsx")
                         else "application/octet-stream")
                return self._send(data, ctype, 200, {
                    "Content-Disposition":
                        f"attachment; filename*=UTF-8''{urllib.parse.quote(os.path.basename(full))}"})

            if path == "/api/report/plan":
                if report_core is None:
                    return self._json(dict(ok=False, error="缺少 report.py"), 500)
                self.store.ensure()
                # rebuild=1：无视现有清单，强制按标记与时序重新生成
                if q.get("rebuild") == "1":
                    items = report_core.suggest_plan(self.store)
                    report_core.save_plan(self.store.dir, items)
                    return self._json(dict(
                        ok=True,
                        items=[it.to_dict() for it in items],
                        groups=[dict(gid=g["gid"],
                                     label=f'{g["gid"]}　{g.get("point","")}',
                                     f13=f"1_3_{g['gid']}.AWA",
                                     f11=f"OCT_{g['gid']}.AWA")
                                for g in self.store.groups()]))

                items = report_core.load_plan(self.store.dir)
                if not items and q.get("suggest") != "0":
                    items = report_core.suggest_plan(self.store)
                    if items:
                        report_core.save_plan(self.store.dir, items)
                return self._json(dict(
                    ok=True,
                    items=[it.to_dict() for it in items],
                    groups=[dict(gid=g["gid"], label=f'{g["gid"]}　{g.get("point","")}',
                                 f13=f"1_3_{g['gid']}.AWA",
                                 f11=f"OCT_{g['gid']}.AWA")
                            for g in self.store.groups()]))

            if path == "/api/report/compute":
                if report_core is None:
                    return self._json(dict(ok=False, error="缺少 report.py"), 500)
                self.store.ensure()
                items = report_core.load_plan(self.store.dir)
                results = report_core.compute_all(self.store, items)
                return self._json(dict(ok=True, rows=[
                    self._report_row(it, r) for it, r in zip(items, results)]))

            if path == "/api/report/detail":
                if report_core is None:
                    return self._json(dict(ok=False, error="缺少 report.py"), 500)
                self.store.ensure()
                idx = int(q.get("i", "0"))
                items = report_core.load_plan(self.store.dir)
                if not (0 <= idx < len(items)):
                    raise ValueError("测点不存在")
                r = report_core.compute(self.store, items[idx])
                return self._json(dict(ok=True, **self._report_detail(r)))

            if path == "/api/ping":
                # 界面定时心跳：窗口关闭后不再请求，启动器据此退出
                touch()
                return self._json(dict(ok=True, version=APP_VERSION,
                                       dir=self.store.dir))

            if path == "/api/config":
                cfg = load_config()
                return self._json(dict(ok=True, dir=self.store.dir,
                                       last=cfg.get("last", ""),
                                       recent=cfg.get("recent", [])))

            if path == "/api/pick-dir":
                picked = pick_folder_dialog(self.store.dir)
                return self._json(dict(ok=True, dir=picked))

            if path == "/api/scan":
                info = self.store.scan(q.get("dir") or None)
                info["ok"] = True
                info["categories"] = self.store.categories()
                info["counts"] = self.store.counts()
                return self._json(info)

            if path == "/api/table":
                cat = q.get("cat", "13OCT")
                organize = q.get("view") == "organize"
                data = self.store.table(cat, organize=organize,
                                        tag_filter=q.get("tag", ""))
                data["ok"] = True
                data["cat"] = cat
                data["organize"] = organize
                data["editCount"] = self.store.edits.count()
                data["tagCounts"] = self.store.tag_counts(cat)
                return self._json(data)

            if path == "/api/edits":
                return self._json(dict(ok=True, count=self.store.edits.count(),
                                       path=self.store.edits.path,
                                       files=self.store.edits.data))

            if path == "/api/groups":
                self.store.ensure()
                return self._json(dict(ok=True, groups=self.store.groups(),
                                       summary=self.store.summary()))

            if path == "/api/detail":
                rec = self.store.detail(q.get("f", ""))
                if rec is None:
                    return self._json(dict(ok=False, error="未找到该文件"), 404)
                rec["ok"] = True
                return self._json(rec)

            if path == "/api/export":
                cat = q.get("cat", "13OCT")
                # files：逗号分隔的文件名，只导出这些行（供整理模块按选中分组导出）
                keep = None
                if q.get("files"):
                    keep = [f for f in q["files"].split(",") if f]
                body, fname, ctype = build_export(
                    cat, self.store, keep, organize=(q.get("view") == "organize"))
                return self._send(body, ctype, 200, {
                    "Content-Disposition":
                        f"attachment; filename*=UTF-8''{urllib.parse.quote(fname)}"})

            if path == "/api/reveal":
                name = q.get("f", "")
                full = os.path.join(self.store.dir, name)
                if not os.path.isfile(full):
                    return self._json(dict(ok=False, error="文件不存在"), 404)
                self._reveal(full)
                return self._json(dict(ok=True))

            # ---- 静态文件
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.normpath(os.path.join(WEB_DIR, rel))
            if not full.startswith(os.path.normpath(WEB_DIR)) or not os.path.isfile(full):
                return self._json(dict(ok=False, error="not found"), 404)
            mime = {".html": "text/html; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".png": "image/png"}.get(os.path.splitext(full)[1].lower(),
                                             "application/octet-stream")
            with open(full, "rb") as f:
                return self._send(f.read(), mime)
        except ValueError as e:
            return self._json(dict(ok=False, error=str(e)), 400)
        except Exception as e:                              # 兜底
            return self._json(dict(ok=False, error=f"{type(e).__name__}: {e}"), 500)

    @staticmethod
    def _reveal(full: str):
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(full)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", full])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(full)])


# ============================================================ 启动 ===
def main(argv):
    args = argv[1:]
    port, root, open_browser = 8765, ROOT_DEFAULT, True
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--port" and i + 1 < len(args):
            port = int(args[i + 1]); i += 2
        elif a == "--dir" and i + 1 < len(args):
            root = args[i + 1]; i += 2
        elif a == "--no-browser":
            open_browser = False; i += 1
        else:
            i += 1

    store = Store(root)
    # ============================================================ 启动器接口 ===
# 供 launcher.py 使用：单独创建服务 + 关窗自动退出

_LAST_TOUCH = [time.time()]


def touch() -> None:
    """界面心跳。每次 HTTP 请求都会刷新，用于判断窗口是否还开着。"""
    _LAST_TOUCH[0] = time.time()


def make_server(root: str, port: int, open_browser: bool = False):
    """创建（不启动）一个绑定好 Store 的 HTTP 服务。"""
    store = Store(root)
    Handler.store = store
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.store = store
    return httpd


def touch_forever(httpd, url: str, idle_seconds: int = 20) -> None:
    """阻塞直到超过 idle_seconds 没有任何请求，然后关闭服务。

    判断依据：页面每 3 秒轮询一次心跳接口；窗口一关，轮询停止。
    """
    # 启动阶段给足缓冲（浏览器冷启动可能慢）
    started = time.time()
    try:
        while True:
            time.sleep(0.5)
            idle = time.time() - _LAST_TOUCH[0]
            if idle > idle_seconds and time.time() - started > idle_seconds:
                break
    except KeyboardInterrupt:
        pass
    finally:
        # shutdown() 会等 serve_forever 的轮询结束（默认 0.5 秒一轮），
        # 再用 daemon 线程兜底，避免关窗后进程滞留
        def _kill():
            try:
                httpd.server_close()
            except Exception:                              # noqa: BLE001
                pass
            os._exit(0)
        threading.Timer(2.0, _kill).start()
        try:
            httpd.shutdown()
        except Exception:                                  # noqa: BLE001
            pass
        try:
            httpd.server_close()
        except Exception:                                  # noqa: BLE001
            pass


def main(argv):
    args = argv[1:]
    port, root, open_browser = 8765, ROOT_DEFAULT, True
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--port" and i + 1 < len(args):
            port = int(args[i + 1]); i += 2
        elif a == "--dir" and i + 1 < len(args):
            root = args[i + 1]; i += 2
        elif a == "--no-browser":
            open_browser = False; i += 1
        else:
            i += 1

    store = Store(root)
    Handler.store = store
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"

    print("=" * 58)
    print("  AWA 声学数据管理 · 本地服务")
    print("=" * 58)
    print(f"  数据目录：{store.dir}")
    print(f"  访问地址：{url}")
    print("  关闭本窗口即停止服务（Ctrl+C）")
    print("=" * 58)

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
