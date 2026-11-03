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
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")
LAST_DIR_FILE = os.path.join(HERE, ".lastdir")      # 记住上次的数据目录
ENV_DIR = os.environ.get("AWA_DATA_DIR", "")


def _read_last_dir() -> str:
    try:
        with open(LAST_DIR_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _write_last_dir(path: str) -> None:
    try:
        with open(LAST_DIR_FILE, "w", encoding="utf-8") as f:
            f.write(path)
    except OSError:
        pass


def default_data_dir() -> str:
    """数据目录优先级：上次使用 > 环境变量 > 上级目录（含 *.AWA）> 上上级。"""
    for cand in (_read_last_dir(), ENV_DIR):
        if cand and os.path.isdir(cand):
            return os.path.abspath(cand)
    parent = os.path.dirname(HERE)
    for cand in (parent, os.path.dirname(parent)):
        if cand and os.path.isdir(cand) and glob.glob(os.path.join(cand, "*.AWA")):
            return os.path.abspath(cand)
    return parent


ROOT_DEFAULT = default_data_dir()

BANDS_ALL = [6.3, 8, 10, 12.5, 16, 20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
             200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500,
             3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000]
METRICS = ["Leq,T", "LFmax", "LFmin", "LSmax", "LSmin"]

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
               bands={}, metrics={}, spl={}, stats={}, dist=[], rows=0,
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
            spl_cols[j] = h2[4:-1]
        elif h2.startswith("W_") and len(h2) == 3:
            spl_cols[j] = h2[2:]

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
                    bands[str(f)] = v
        spl = {}
        for j, k in spl_cols.items():
            if j < len(cols):
                v = num(cols[j])
                if v is not None:
                    spl[k] = v
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
        if stats:
            rec["stats"][metric] = stats

    rec["bands"] = rec["metrics"].get("Leq,T", {})
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
                                     metrics={}, spl={}, stats={}, dist=[],
                                     rows=0, error=str(e))
        self.records, self.errors = records, errors
        self.elapsed_ms = (time.perf_counter() - t0) * 1000
        self.scanned_at = time.time()
        _write_last_dir(self.dir)
        return dict(dir=self.dir, elapsedMs=round(self.elapsed_ms, 1),
                    files=len(records), errors=errors,
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

    def table(self, cat: str) -> dict:
        """返回 {headers, rows, note}；rows 首列为序号，第二列为文件名。"""
        self.ensure()
        c = self.counts()
        if cat in ("13OCT", "OCT"):
            kind = "1/3OCT" if cat == "13OCT" else "OCT"
            files = [r for r in self._sorted() if r["kind"] == kind]
            headers = [
                ("序号", 52), ("文件名", 128), ("测点名", 96), ("测试日期", 96),
                ("测试时间", 84), ("经历时间", 86), ("SPL(A)", 68),
                ("SPL(C)", 68), ("SPL(Z)", 68), ("Leq,T (A)", 78),
            ]
            rows = []
            for i, r in enumerate(files, 1):
                spl = r["spl"].get("Leq,T", {})
                rows.append([str(i), r["file"], r["point"], r["date"], r["time"],
                             r["ts"], self._f(spl.get("A")), self._f(spl.get("C")),
                             self._f(spl.get("Z")), self._f(spl.get("A"))])
            return dict(headers=headers, rows=rows, kind="spectrum",
                        note=f"共 {len(files)} 份 {kind} 文件，每份含 5 行统计量")

        if cat == "STA":
            files = [r for r in self._sorted() if r["kind"] == "STA"]
            headers = [("序号", 52), ("文件名", 128), ("测点名", 96), ("测试日期", 96),
                       ("测试时间", 84), ("LeqT", 64), ("Lmax", 64), ("Lmin", 64),
                       ("L10", 60), ("L50", 60), ("L90", 60), ("L95", 60),
                       ("SD", 56), ("SEL", 64)]
            rows = []
            for i, r in enumerate(files, 1):
                st = next(iter(r["stats"].values()), {})
                rows.append([str(i), r["file"], r["point"], r["date"], r["time"]] +
                            [self._f(st.get(k)) for k in
                             ("LeqT", "Lmax", "Lmin", "L10", "L50", "L90",
                              "L95", "SD", "SEL")])
            return dict(headers=headers, rows=rows, kind="stats",
                        note=f"共 {len(files)} 份 STA 统计文件")

        if cat == "TOTAL":
            headers = [("序号", 52), ("文件名", 128), ("测点名", 96), ("测试日期", 96),
                       ("指标", 74), ("SPL(A)", 68), ("SPL(C)", 68), ("SPL(Z)", 68),
                       ("SPL(U)", 68), ("SPL(T)", 68), ("SPL(B)", 68)]
            rows = []
            n = 0
            for r in self._sorted():
                if not r["spl"]:
                    continue
                for metric in METRICS:
                    if metric not in r["spl"]:
                        continue
                    spl = r["spl"][metric]
                    n += 1
                    rows.append([str(n), r["file"], r["point"], r["date"], metric] +
                                [self._f(spl.get(k)) for k in
                                 ("A", "C", "Z", "U", "T", "B")])
            return dict(headers=headers, rows=rows, kind="total",
                        note=f"从 {sum(1 for r in self.records.values() if r['spl'])} "
                             f"份频谱文件中提取 {n} 条总值记录")

        if cat == "NUM":
            files = [r for r in self._sorted() if r["kind"] == "NUM"]
            headers = [("序号", 52), ("文件名", 128), ("测点名", 96), ("测试日期", 96),
                       ("声级范围 (dB)", 118), ("峰值档位 (dB)", 104),
                       ("最大占比 (%)", 104), ("分布档数", 84)]
            rows = []
            for i, r in enumerate(files, 1):
                d = r["dist"]
                meta = self._sibling(r["file"]) or {}
                point = r["point"] or meta.get("point", "")
                date = r["date"] or meta.get("date", "")
                if d:
                    lo, hi = d[0][0], d[-1][0]
                    pk = max(d, key=lambda x: x[1])
                    rows.append([str(i), r["file"], point, date,
                                 f"{lo:.0f} ~ {hi:.0f}", f"{pk[0]:.0f}",
                                 f"{pk[1]:.2f}", str(len(d))])
                else:
                    rows.append([str(i), r["file"], point, date,
                                 "—", "—", "—", "0"])
            return dict(headers=headers, rows=rows, kind="num",
                        note=f"共 {len(files)} 份声级分布文件")

        return dict(headers=[("序号", 52), ("文件名", 128)], rows=[], kind="empty",
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
    def detail(self, name: str) -> dict | None:
        r = self.records.get(name)
        if r is None:
            return None
        out = dict(r)
        out["file"] = name
        # 只保留有效频带，前端按数值排序
        for m, bands in out["metrics"].items():
            out["metrics"][m] = {k: v for k, v in bands.items()
                                 if float(k) in BANDS_ALL}
        return out


# ============================================================ 导出 ===
def build_export(cat: str, store: Store):
    data = store.table(cat)
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
    server_version = "AWADataManager/1.0"
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
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        path = u.path

        try:
            if path == "/api/scan":
                info = self.store.scan(q.get("dir") or None)
                info["ok"] = True
                info["categories"] = self.store.categories()
                info["counts"] = self.store.counts()
                return self._json(info)

            if path == "/api/table":
                cat = q.get("cat", "13OCT")
                data = self.store.table(cat)
                data["ok"] = True
                data["cat"] = cat
                return self._json(data)

            if path == "/api/detail":
                rec = self.store.detail(q.get("f", ""))
                if rec is None:
                    return self._json(dict(ok=False, error="未找到该文件"), 404)
                rec["ok"] = True
                return self._json(rec)

            if path == "/api/export":
                cat = q.get("cat", "13OCT")
                body, fname, ctype = build_export(cat, self.store)
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
