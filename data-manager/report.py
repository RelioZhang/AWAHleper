#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AWA 报告生成 · 计算内核
=================================================
从 AWA 原始数据直接算出「报告表格 + 曲线」需要的数值，不依赖 Qt。

覆盖两类测点：
  · 噪声级  —— 1/1 倍频程 63Hz~8kHz + NR/NC（仪器已算好，优先取仪器值）
  · 隔声    —— 1/3 倍频程 100Hz~5kHz 的声压级差 NR，按 ASTM E413 判 NIC

数值口径（与原 02-NIC计算 脚本一致，勿随意改）：
  · NR = 内 - 外，先保留 1 位小数，判级前取整（ASTM E413 要求整数频谱）
  · 判级只用 125Hz~4000Hz 共 16 个频带
  · 轮廓 [-16,-13,-10,-7,-4,-1,0,1,2,3,4,4,4,4,4,4]
  · 总不利偏差 ≤ 32 且单点 ≤ 8
  · 负 NIC 保留负值（不外显为 0），便于发现配错

只做计算与写表，不出图、不碰界面。
"""

from __future__ import annotations

import json
import math
import os

try:                                        # 导出 xlsx 才需要
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    HAS_XLSX = True
except Exception:                           # noqa: BLE001
    Workbook = None
    HAS_XLSX = False


# ============================================================ 常量 ===
# 1/3 倍频程：报告表 3.2/3.3 用的 18 个频带（100Hz~5kHz）
BANDS_THIRD = [100, 125, 160, 200, 250, 315, 400, 500, 630,
               800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000]

# 1/1 倍频程：报告表 3.1-1 用的 8 个频带（63Hz~8kHz）
BANDS_OCT = [63, 125, 250, 500, 1000, 2000, 4000, 8000]

# ASTM E413 标准轮廓（125Hz~4000Hz，500Hz 处为 0）
NIC_CONTOUR = [-16, -13, -10, -7, -4, -1, 0, 1, 2, 3, 4, 4, 4, 4, 4, 4]
NIC_MAX_TOTAL = 32          # 总不利偏差上限
NIC_MAX_SINGLE = 8          # 单频带不利偏差上限

# ANSI S1.2 / ASHRAE NC 曲线（仪器没给 NC 时用它反算）
NC_TABLE = {
    15: [47, 36, 29, 22, 17, 14, 12, 11],
    20: [51, 40, 33, 26, 22, 19, 17, 16],
    25: [54, 44, 37, 31, 27, 24, 22, 21],
    30: [57, 48, 41, 35, 31, 29, 28, 27],
    35: [60, 52, 45, 40, 36, 34, 33, 32],
    40: [64, 56, 50, 45, 41, 39, 38, 37],
    45: [67, 60, 54, 50, 47, 45, 44, 43],
    50: [71, 64, 58, 54, 52, 51, 50, 49],
    55: [74, 67, 62, 58, 56, 56, 55, 54],
    60: [77, 71, 67, 63, 61, 61, 60, 59],
    65: [80, 75, 71, 68, 66, 66, 65, 64],
    70: [83, 79, 75, 72, 71, 70, 69, 68],
}

PLAN_FILE = ".report-plan.json"     # 测点清单（存在数据目录，跟着项目走）

KIND_NOISE = "噪声级"
KIND_INSUL = "隔声"


# ============================================================ 基础工具 ===
def band_key(hz) -> str:
    """频带 -> 解析结果里的键（1000.0 -> '1000'，31.5 -> '31.5'）。"""
    f = float(hz)
    return str(int(f)) if f == int(f) else str(f)


def band_text(hz) -> str:
    """频带 -> 报告里的写法：1000 -> 1k，1250 -> 1.25k。"""
    f = float(hz)
    if f >= 1000:
        return f"{f / 1000:.4f}".rstrip("0").rstrip(".") + "k"
    return f"{f:.2f}".rstrip("0").rstrip(".")


def half_up(x: float) -> int:
    """四舍五入（Python 内置 round 是银行家舍入，判级不能用它）。"""
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def fmt_rating(kind: str, n: int) -> str:
    """评级写法：NIC-28 / NC-25；负值写成 NIC(-4)，免得出现 NIC--4。"""
    pre = "NC" if kind == KIND_NOISE else "NIC"
    return f"{pre}-{n}" if n >= 0 else f"{pre}({n})"


# ============================================================ 隔声计算 ===
def nic_of(nr: list[float]) -> int:
    """ASTM E413：由 18 个 1/3 倍频程声压级差判 NIC。

    nr 的长度必须是 18（100Hz~5kHz）；判级只取中间 16 个（125Hz~4kHz）。
    """
    if len(nr) != len(BANDS_THIRD):
        raise ValueError(f"NR 需要 {len(BANDS_THIRD)} 个频带，实际 {len(nr)} 个")
    core = [half_up(v) for v in nr[1:17]]
    for guess in range(120, -41, -1):        # 上限放宽到 120，下限到 -40
        contour = [c + guess for c in NIC_CONTOUR]
        deficits = [max(0, c - v) for c, v in zip(contour, core)]
        if sum(deficits) <= NIC_MAX_TOTAL and max(deficits) <= NIC_MAX_SINGLE:
            return guess
    return -40


def nic_contour_at(nic: int, band_hz: int):
    """给定 NIC，取该频带上的轮廓值（超出 125~4k 返回 None）。"""
    if band_hz not in BANDS_THIRD:
        return None
    i = BANDS_THIRD.index(band_hz)
    if 1 <= i <= 16:
        return NIC_CONTOUR[i - 1] + nic
    return None


def deficiencies(nr: list[float], nic: int) -> list[int]:
    """逐频带的不利偏差（>0 表示该频带没达标），用于画阴影。"""
    out = []
    for hz, v in zip(BANDS_THIRD, nr):
        c = nic_contour_at(nic, hz)
        out.append(0 if c is None else max(0, c - half_up(v)))
    return out


# ============================================================ 噪声级计算 ===
def nc_of(oct_values: list[float]) -> int:
    """由 8 个倍频程声级反算 NC（仪器没给时用）。

    做法：每个频带把测量值反插到 NC 曲线族上得到一个 NC 值，
    取全频带最大值作为该频谱的 NC 评级。
    """
    if len(oct_values) != len(BANDS_OCT):
        raise ValueError("倍频程需要 8 个频带")
    levels = sorted(NC_TABLE)
    best = None
    for i, hz in enumerate(BANDS_OCT):
        v = oct_values[i]
        if v is None:
            continue
        got = None
        for a, b in zip(levels, levels[1:]):
            lo, hi = NC_TABLE[a][i], NC_TABLE[b][i]
            if lo <= v <= hi and hi > lo:
                got = a + (b - a) * (v - lo) / (hi - lo)
                break
        if got is None:
            got = levels[0] if v < NC_TABLE[levels[0]][i] else levels[-1]
        best = got if best is None else max(best, got)
    return half_up(best) if best is not None else 0


# ============================================================ 单个测点 ===
def read_oct(store, file: str):
    """读 1/1 倍频程测点 -> (8 个频带值, NC, NR)。缺频带返回 None。"""
    rec = store.detail(file, organize=True) if store else None
    if not rec:
        return None, None, None
    bands = rec.get("metrics", {}).get("Leq,T", {})
    vals = [bands.get(band_key(hz)) for hz in BANDS_OCT]
    if sum(v is not None for v in vals) < 6:
        return None, None, None
    rating = rec.get("rating", {}).get("Leq,T", {})
    nc = rating.get("NC")
    nr = rating.get("NR")
    if nc is None and all(v is not None for v in vals):
        nc = nc_of(vals)
    return ([v if v is not None else 0.0 for v in vals],
            None if nc is None else int(round(nc)),
            None if nr is None else int(round(nr)))


def read_nr(store, inner: str, outer: str):
    """读一对 1/3 倍频程测点 -> 18 个频带的声压级差（内 - 外）。"""
    a = store.detail(inner, organize=True)
    b = store.detail(outer, organize=True)
    if not a or not b:
        return None
    ba = a.get("metrics", {}).get("Leq,T", {})
    bb = b.get("metrics", {}).get("Leq,T", {})
    out = []
    for hz in BANDS_THIRD:
        k = band_key(hz)
        va, vb = ba.get(k), bb.get(k)
        if va is None or vb is None:
            return None
        out.append(round(va - vb, 1))
    return out


# ============================================================ 测点清单 ===
class Item:
    """一个报告测点。kind=噪声级时只看 file；kind=隔声时看 inner/outer。"""

    def __init__(self, name="", kind=KIND_INSUL, table="", order=0,
                 file="", inner="", outer="", design="", room="", cond="",
                 shift=0.0):
        self.name = name
        self.kind = kind
        self.table = table          # 表号，如 3.2-1
        self.order = order
        self.file = file            # 噪声级用
        self.inner = inner          # 隔声：内侧（声源侧）
        self.outer = outer          # 隔声：外侧（接收侧）
        self.design = design        # 设计值，如 NIC-28+ / NC-30
        self.room = room            # 噪声级：房间分组，如 0806 大床房
        self.cond = cond            # 噪声级：工况，如 FCU 低速
        self.shift = shift          # 隔声：声压级差整体平移量（dB，消除干扰）

    def to_dict(self) -> dict:
        return dict(name=self.name, kind=self.kind, table=self.table,
                    order=self.order, file=self.file, inner=self.inner,
                    outer=self.outer, design=self.design, room=self.room,
                    cond=self.cond, shift=self.shift)

    @staticmethod
    def from_dict(d: dict) -> "Item":
        it = Item()
        for k in ("name", "kind", "table", "file", "inner", "outer",
                  "design", "room", "cond"):
            setattr(it, k, d.get(k, "") or "")
        it.kind = it.kind if it.kind in (KIND_NOISE, KIND_INSUL) else KIND_INSUL
        try:
            it.order = int(d.get("order", 0) or 0)
        except (TypeError, ValueError):
            it.order = 0
        try:
            it.shift = float(d.get("shift", 0) or 0)
        except (TypeError, ValueError):
            it.shift = 0.0
        return it


def plan_path(data_dir: str) -> str:
    return os.path.join(data_dir, PLAN_FILE)


def tag_of(store, name: str) -> str:
    """某个文件所属测量组在【数据整理】里打的标记：噪声级 / 隔声 / 空。

    报告只认标记过的数据——没标记就说明测点归属还没确认，
    不允许出现在报告里（来源必须可追溯）。
    """
    if not store or not name:
        return ""
    try:
        return store.edits.get_tag(store.group_of(name)) or ""
    except Exception:                       # noqa: BLE001
        return ""


def load_plan(data_dir: str) -> list[Item]:
    p = plan_path(data_dir)
    if not os.path.isfile(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [Item.from_dict(d) for d in data.get("items", [])]
    except Exception:                       # noqa: BLE001
        return []


def save_plan(data_dir: str, items: list[Item]) -> None:
    with open(plan_path(data_dir), "w", encoding="utf-8") as f:
        json.dump({"version": 1,
                   "savedAt": __import__("datetime").datetime.now()
                   .strftime("%Y-%m-%d %H:%M:%S"),
                   "items": [it.to_dict() for it in items]},
                  f, ensure_ascii=False, indent=1)


def load_plan_checked(store) -> list[Item]:
    """读清单，顺手剔掉不该出现的隔声行。

    早先的草稿会把任意 1/3OCT 两两配对（一次能冒出十几组），
    这些行没有标记背书，不能留在清单里。这里按「隔声」标记清理，
    清完顺手写回，下次打开就是干净的。
    """
    items = load_plan(store.dir)
    if not items:
        return items

    keep, dropped = [], 0
    for it in items:
        if it.kind == KIND_INSUL:
            bad = any(f and (f not in store.records or tag_of(store, f) != KIND_INSUL)
                      for f in (it.inner, it.outer))
            if bad:
                dropped += 1
                continue
        keep.append(it)

    if dropped:
        for i, it in enumerate(keep, 1):
            it.order = i
        save_plan(store.dir, keep)
    return keep


def suggest_plan(store) -> list[Item]:
    """首次进入报告页时给一份草稿：按标记和测量时间自动配对。

    只做「能猜的部分」：噪声级组直接成行；隔声组按时间相邻配对，
    配出来的结果仍要人工确认（配错会在结果列标红）。
    """
    groups = store.groups() if store else []
    noise_groups = []
    insul_groups = []
    for g in groups:
        tag = ""
        try:
            tag = (store.edits.data.get("_tags", {}) or {}).get(g["gid"], "")
        except Exception:                   # noqa: BLE001
            tag = ""
        # 只收「明确打了标记」的组；未标记的数据不进报告，
        # 否则报告里会出现来源不明的行（2026-11-04 需求 25）
        if tag == KIND_NOISE:
            noise_groups.append(g)
        elif tag == KIND_INSUL:
            insul_groups.append(g)

    items = []
    for i, g in enumerate(noise_groups, 1):
        f = f"OCT_{g['gid']}.AWA"
        if f not in store.records:
            continue
        items.append(Item(name=g.get("point") or f"测点{i}",
                          kind=KIND_NOISE, table="3.1-1", order=i, file=f))

    # 隔声：按测量时间两两配对（内 / 外）。配错会在结果列暴露出来，
    # 比让人从 30 多个编号里手工挑两个要快得多。
    insul_groups.sort(key=lambda g: (g.get("date") or "", g.get("time") or ""))
    seq = 0
    for i in range(0, len(insul_groups), 2):
        a = insul_groups[i]
        b = insul_groups[i + 1] if i + 1 < len(insul_groups) else None
        f_in = f"1_3_{a['gid']}.AWA"
        if f_in not in store.records:
            continue
        seq += 1
        items.append(Item(
            name=a.get("point") or f"隔声测点{seq}",
            kind=KIND_INSUL, order=seq,
            inner=f_in,
            outer=(f"1_3_{b['gid']}.AWA" if b else "")))
    return items


# ============================================================ 批量计算 ===
class Result:
    def __init__(self, item: Item):
        self.item = item
        self.ok = False
        self.error = ""
        self.bands: list = []       # 噪声级：8 个倍频程值；隔声：18 个 NR
        self.nc = None
        self.nr_instrument = None
        self.nic = None
        self.deficit: list = []
        self.pass_ = None           # True/False/None（没填设计值就是 None）
        self.shift = 0.0            # 隔声：平移量
        self.raw_bands: list = []   # 隔声：平移前的原始声压级差

    @property
    def value_num(self):
        """实测评级的数字部分：NIC-28 -> 28，NC-25 -> 25。"""
        if self.item.kind == KIND_NOISE:
            return None if self.nc is None else int(self.nc)
        return None if self.nic is None else int(self.nic)

    @property
    def value(self):
        n = self.value_num
        if n is None:
            return None
        return fmt_rating(self.item.kind, n)

    @property
    def design_num(self):
        """从设计值里抠出数字：NIC-28+ -> 28，NC-30 -> 30。"""
        s = (self.item.design or "").replace("＋", "+").replace(" ", "")
        digits = ""
        for ch in s:
            if ch.isdigit():
                digits += ch
            elif digits:
                break
        return int(digits) if digits else None


def compute(store, item: Item) -> Result:
    r = Result(item)
    if not store:
        r.error = "未读取数据"
        return r

    if item.kind == KIND_NOISE:
        if not item.file:
            r.error = "未选择文件"
            return r
        vals, nc, nr = read_oct(store, item.file)
        if vals is None:
            r.error = "该文件缺少倍频程数据"
            return r
        r.bands = vals
        r.nc = nc
        r.nr_instrument = nr
        r.ok = True
    else:
        if not item.inner or not item.outer:
            r.error = "内/外文件没选全"
            return r
        # 硬门槛：两侧都必须在【数据整理】里标成「隔声」，
        # 没标记的 1/3OCT 数据一律不出数（2026-11-04 需求）
        miss = [f for f in (item.inner, item.outer) if tag_of(store, f) != KIND_INSUL]
        if miss:
            r.error = "未在【数据整理】标为「隔声」：" + "、".join(miss)
            return r
        nr = read_nr(store, item.inner, item.outer)
        if nr is None:
            r.error = "两侧频带数据不完整，无法相减"
            return r
        # 平移：现场存在背景噪声/侧向传声等干扰时，整条曲线上下平移还原隔声量
        shift = float(item.shift or 0)
        if shift:
            nr = [round(v + shift, 1) for v in nr]
        r.shift = shift
        r.raw_bands = list(read_nr(store, item.inner, item.outer) or [])
        r.bands = nr
        r.nic = nic_of(nr)
        r.deficit = deficiencies(nr, r.nic)
        r.ok = True

    d = r.design_num
    got = r.value_num
    if d is not None and got is not None:
        # 噪声级是限值：实测越小越好；隔声量是要求：实测越大越好
        r.pass_ = (got <= d) if item.kind == KIND_NOISE else (got >= d)
    return r


def compute_all(store, items: list[Item]) -> list[Result]:
    return [compute(store, it) for it in items]


# ============================================================ 写出 xlsx ===
_THIN = Side(style="thin", color="BFCEDC")
BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
HEAD_FILL = PatternFill("solid", fgColor="EEF4FA")
HEAD_FONT = Font(name="微软雅黑", size=9, bold=True, color="3D4F61")
CELL_FONT = Font(name="微软雅黑", size=9, color="2B3947")
TITLE_FONT = Font(name="微软雅黑", size=10, bold=True, color="1B5F98")
CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")


def _style_cell(c, font=CELL_FONT, align=CENTER, fill=None):
    c.font = font
    c.alignment = align
    c.border = BORDER
    if fill:
        c.fill = fill


def write_xlsx(results: list[Result], out_path: str,
               meta: dict | None = None) -> str:
    """把算好的结果写成报告可直接抄的 xlsx。

    三张表：
      概要     —— 一测点一行，带结果、设计值、判定
      噪声级   —— 表 3.1-1 的版式：8 个倍频带 x 各测点，末尾 NC 实测/设计
      隔声     —— 每个测点一张小表（18 频带分两栏 + NIC）
    """
    if not HAS_XLSX:
        raise RuntimeError("缺少 openpyxl，无法生成 xlsx")

    wb = Workbook()
    meta = meta or {}

    # ---------------- 概要 ----------------
    ws = wb.active
    ws.title = "概要"
    ws.column_dimensions["A"].width = 6
    for col, w in zip("BCDEFGHI", (26, 11, 15, 26, 26, 13, 11, 12)):
        ws.column_dimensions[col].width = w

    head = ["序号", "测点名称", "类型", "表号", "内侧/文件", "外侧文件",
            "实测值", "设计值", "判定"]
    for j, h in enumerate(head, 1):
        c = ws.cell(1, j, h)
        _style_cell(c, HEAD_FONT, CENTER, HEAD_FILL)
    ws.freeze_panes = "A2"

    for i, r in enumerate(results, 1):
        it = r.item
        row = [i, it.name, it.kind, it.table,
               it.file or it.inner, it.outer,
               r.value or r.error,
               it.design or "—",
               "—" if r.pass_ is None else ("满足" if r.pass_ else "不满足")]
        for j, v in enumerate(row, 1):
            c = ws.cell(i + 1, j, v)
            _style_cell(c, CELL_FONT, LEFT if j in (2, 5, 6) else CENTER)
        if r.pass_ is False:
            ws.cell(i + 1, 9).font = Font(name="微软雅黑", size=9,
                                          bold=True, color="B8413A")
        if not r.ok:
            ws.cell(i + 1, 7).font = Font(name="微软雅黑", size=9, color="A8700F")

    # ---------------- 噪声级 ----------------
    noise = [r for r in results if r.item.kind == KIND_NOISE and r.ok]
    if noise:
        ws = wb.create_sheet("噪声级")
        n = len(noise)
        ws.cell(1, 1, "表 3.1-1 客房室内噪声级实测结果").font = TITLE_FONT
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n + 1)

        # 表头两行：房间（合并）+ 工况。
        # 房间取 item.room，没填就退回 item.name；工况取 name 里冒号后半段或单独字段。
        def room_of(r):
            return (r.item.room or r.item.name or "").strip()

        def cond_of(r):
            c = (r.item.cond or "").strip()
            if c:
                return c
            nm = (r.item.name or "").strip()
            for sep in ("/", "-", "·", " "):
                if sep in nm:
                    tail = nm.split(sep)[-1].strip()
                    if tail and tail != room_of(r):
                        return tail
            return ""

        hz_col = 1
        _style_cell(ws.cell(2, hz_col, "倍频带\n中心频率\n(Hz)"), HEAD_FONT, CENTER, HEAD_FILL)
        ws.merge_cells(start_row=2, start_column=hz_col, end_row=3, end_column=hz_col)

        col = 2
        groups = []                      # [(room, start_col, count)]
        for r in noise:
            rm = room_of(r)
            if groups and groups[-1][0] == rm:
                groups[-1][2] += 1
            else:
                groups.append([rm, col, 1])
            col += 1

        for rm, start, cnt in groups:
            if cnt > 1:
                ws.merge_cells(start_row=2, start_column=start,
                               end_row=2, end_column=start + cnt - 1)
            _style_cell(ws.cell(2, start, rm), HEAD_FONT, CENTER, HEAD_FILL)
            if cnt > 1:
                for k in range(cnt):
                    _style_cell(ws.cell(2, start + k), HEAD_FONT, CENTER, HEAD_FILL)

        for j, r in enumerate(noise, 2):
            label = cond_of(r) or f"测点{j - 1}"
            _style_cell(ws.cell(3, j, label), HEAD_FONT, CENTER, HEAD_FILL)

        ws.row_dimensions[2].height = 22
        ws.row_dimensions[3].height = 22
        ws.column_dimensions["A"].width = 16
        for j in range(2, n + 2):
            ws.column_dimensions[get_column_letter(j)].width = 11
        ws.freeze_panes = "B4"

        for i, hz in enumerate(BANDS_OCT, 4):
            _style_cell(ws.cell(i, 1, int(hz) if hz >= 1000 else hz))
            for j, r in enumerate(noise, 2):
                v = r.bands[i - 4]
                c = ws.cell(i, j, round(v, 1))
                _style_cell(c)
                c.number_format = "0.0"

        base = 4 + len(BANDS_OCT)
        for k, (label, getter) in enumerate((
                ("NC（实测值）", lambda r: (fmt_rating(KIND_NOISE, r.nc)
                                            if r.nc is not None else "—")),
                ("NC（设计值）", lambda r: r.item.design or "—"))):
            _style_cell(ws.cell(base + k, 1, label), HEAD_FONT, LEFT)
            for j, r in enumerate(noise, 2):
                _style_cell(ws.cell(base + k, j, getter(r)))

    # ---------------- 隔声 ----------------
    insul = [r for r in results if r.item.kind == KIND_INSUL and r.ok]
    if insul:
        ws = wb.create_sheet("隔声")
        row = 1
        for idx, r in enumerate(insul, 1):
            it = r.item
            title = f"表 {it.table or ('3.2-%d' % idx)} {it.name} 空气声隔声实测结果"
            ws.cell(row, 1, title).font = TITLE_FONT
            ws.merge_cells(start_row=row, start_column=1,
                           end_row=row, end_column=4)
            row += 1

            for j, h in enumerate(("1/3 倍频带 中心频率(Hz)", "声压级差 NR(dB)",
                                   "1/3 倍频带 中心频率(Hz)", "声压级差 NR(dB)"), 1):
                _style_cell(ws.cell(row, j, h), HEAD_FONT, CENTER, HEAD_FILL)
            row += 1

            half = len(BANDS_THIRD) // 2        # 18 -> 9 + 9
            top = row
            for i in range(half):
                a, b = i, i + half
                _style_cell(ws.cell(top + i, 1, band_text(BANDS_THIRD[a])))
                _style_cell(ws.cell(top + i, 2, half_up(r.bands[a])))
                _style_cell(ws.cell(top + i, 3, band_text(BANDS_THIRD[b])))
                _style_cell(ws.cell(top + i, 4, half_up(r.bands[b])))
            row = top + half

            _style_cell(ws.cell(row, 1, "NIC（实测值）"), HEAD_FONT, LEFT)
            _style_cell(ws.cell(row, 2, fmt_rating(KIND_INSUL, r.nic)))
            _style_cell(ws.cell(row, 3, "NIC（设计值）"), HEAD_FONT, LEFT)
            _style_cell(ws.cell(row, 4, it.design or "—"))
            row += 3

        ws.column_dimensions["A"].width = 22
        ws.column_dimensions["B"].width = 16
        ws.column_dimensions["C"].width = 22
        ws.column_dimensions["D"].width = 16

    # ---------------- 说明 ----------------
    ws = wb.create_sheet("说明")
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 92
    notes = [
        ("数据来源", meta.get("数据目录", "")),
        ("项目", meta.get("项目", "")),
        ("生成时间", meta.get("生成时间", "")),
        ("", ""),
        ("噪声级", "倍频程 63Hz~8kHz 取各测点 Leq,T；NC 优先用仪器算好的值，"
                   "仪器未给时按 ANSI S1.2 曲线族反插得到。"),
        ("隔声", "声压级差 NR = 内侧 - 外侧，18 个 1/3 倍频程（100Hz~5kHz），"
                 "表内按整数呈现。"),
        ("隔声来源", "只取【数据整理】里标为「隔声」的 1/3OCT 测量；"
                     "没有标记的数据不会进入报告。"),
        ("NIC", "ASTM E413：只用 125Hz~4000Hz 共 16 个频带判级，"
                "轮廓[-16…4]，总不利偏差 ≤32 且单点 ≤8。"),
        ("负值", "NIC 若为负数说明外侧比内侧还响，多半是内/外文件配错了，"
                 "请回到清单核对。"),
    ]
    for i, (a, b) in enumerate(notes, 1):
        _style_cell(ws.cell(i, 1, a), HEAD_FONT, LEFT)
        c = ws.cell(i, 2, b)
        _style_cell(c, CELL_FONT, LEFT)

    wb.save(out_path)
    return out_path


# ============================================================ 命令行自查 ===
if __name__ == "__main__":                  # pragma: no cover
    import argparse
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import server as core

    ap = argparse.ArgumentParser(description="报告数据自检")
    ap.add_argument("dir", nargs="?", default=".")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    st = core.Store(args.dir)
    st.scan()
    print(f"扫描到 {len(st.records)} 个文件，{len(st.groups())} 组测量")

    items = load_plan_checked(st)
    if not items:
        items = suggest_plan(st)
        save_plan(args.dir, items)
        print(f"首次运行，已生成测点清单草稿（{len(items)} 行）："
              f"{plan_path(args.dir)}")
        print("请填好内/外文件和设计值后重跑。")
        sys.exit(0)

    res = compute_all(st, items)
    for r in res:
        flag = "" if r.ok else f"  ! {r.error}"
        print(f"  {r.item.name:<24}{r.value or '—':>10}"
              f"  设计 {r.item.design or '—':<10}{flag}")
    if args.out:
        write_xlsx(res, args.out, {"数据目录": os.path.abspath(args.dir)})
        print("已写出", args.out)
