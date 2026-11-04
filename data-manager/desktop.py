#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AWA 数据管理 · 原生桌面版
=================================================
复用 server.py 的解析 / 侧车 / 批量逻辑，界面改用 Qt（PySide6）。

运行：
    python desktop.py
    python desktop.py --dir D:\\某批数据

依赖：
    pip install PySide6
    （只用这一个第三方库；数据解析部分仍为零依赖）

界面行为：
    · 数据管理：只读查看，不可修改
    · 数据整理：同一界面，但单元格可单击编辑、Tab 跳格、可粘贴
    · 原始 AWA 文件永不改写，改动全部记在数据目录的 .awa-edits.json
"""

from __future__ import annotations

import os
import sys

# 让自己所在目录可导入 server.py
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    from PySide6.QtCore import (Qt, QAbstractTableModel, QModelIndex, QSize,
                                QSortFilterProxyModel, Signal)
    from PySide6.QtGui import (QAction, QColor, QFont, QIcon, QKeySequence,
                               QPainter, QPen, QBrush, QPixmap, QShortcut)
    from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog,
                                   QFrame, QHBoxLayout, QHeaderView, QLabel,
                                   QLineEdit, QMainWindow, QMessageBox,
                                   QPushButton, QSplitter, QStackedWidget,
                                   QStatusBar, QTableView, QToolBar,
                                   QVBoxLayout, QWidget, QAbstractItemView,
                                   QSizePolicy)
except ImportError:                                    # pragma: no cover
    sys.stderr.write(
        "\n缺少依赖 PySide6。请在命令行执行：\n\n"
        "    pip install PySide6\n\n"
        "安装完成后重新运行本程序。\n")
    sys.exit(2)

import server as core


# ============================================================ 调色板 ===
class C:
    BG = "#eef2f6"
    PANEL = "#ffffff"
    SIDE = "#f7fafd"
    LINE = "#dbe5ef"
    LINE_SOFT = "#eaf1f8"
    TEXT = "#2b3947"
    TEXT2 = "#5b6b7b"
    TEXT3 = "#94a3b3"
    BLUE = "#2b7fc4"
    BLUE_DEEP = "#1b5f98"
    BLUE_BG = "#e8f2fb"
    CHIP_BLUE_BG = "#f7fbff"
    WARN = "#a8700f"
    WARN_BG = "#fffaea"
    OK = "#2c6b48"
    OK_BG = "#f3fbf5"
    DURTY = "#fff8e1"
    SEl = "#d8ebfa"
    NOISE_BG = "#fff8e6"
    INSUL_BG = "#eef7f1"


STYLE = f"""
QWidget {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 12px;
    color: {C.TEXT};
}}
QMainWindow, QWidget#central {{ background: {C.BG}; }}

/* 顶部模块栏 */
QWidget#modbar {{ background: {C.PANEL}; border-bottom: 1px solid {C.LINE}; }}
QPushButton#modbtn {{
    border: 0; padding: 0 16px; height: 34px;
    color: {C.TEXT2}; background: transparent; font-size: 12.5px;
}}
QPushButton#modbtn:hover {{ background: {C.CHIP_BLUE_BG}; color: {C.BLUE_DEEP}; }}
QPushButton#modbtn:checked {{
    color: {C.BLUE_DEEP}; font-weight: 700;
    border-bottom: 2px solid {C.BLUE};
}}

/* 工具按钮 */
QPushButton#act {{
    border: 1px solid {C.LINE}; border-radius: 3px;
    padding: 0 11px; height: 26px; background: #fff; color: #33506b;
}}
QPushButton#act:hover {{ border-color: #9dc3e3; color: {C.BLUE_DEEP}; }}
QPushButton#act:disabled {{ color: #b6c2ce; background: #f8fbfd; }}
QPushButton#act[primary="true"] {{
    border-color: #7fb4dd; background: #eaf4fd;
    color: #14538a; font-weight: 700;
}}
QPushButton#act[danger="true"]:hover {{ border-color: #e3a8a3; color: #b8413a; }}

/* 侧栏 */
QWidget#sidebar {{ background: {C.SIDE}; border-right: 1px solid {C.LINE}; }}
QLabel#sidehead {{
    padding: 8px 12px; font-weight: 700; color: #2c4b66;
    background: #eef5fb; border-bottom: 1px solid {C.LINE};
}}
QListWidget#catlist {{
    border: 0; background: transparent; outline: 0;
}}
QListWidget#catlist::item {{
    height: 34px; padding-left: 12px; color: {C.TEXT};
    border-bottom: 1px solid {C.LINE_SOFT};
}}
QListWidget#catlist::item:hover {{ background: #eaf4fd; }}
QListWidget#catlist::item:selected {{
    background: {C.BLUE_BG}; color: {C.BLUE_DEEP};
    border-left: 3px solid {C.BLUE};
}}

/* 表格 */
QTableView {{
    background: #fff; border: 0;
    gridline-color: #eef3f8;
    selection-background-color: {C.SEl};
    selection-color: {C.TEXT};
    outline: 0;
}}
QTableView::item {{ padding: 0 6px; border-right: 1px solid {C.LINE_SOFT}; }}
QHeaderView::section {{
    background: #eef4fa; color: #3d4f61; font-weight: 700;
    padding: 0 6px; height: 27px;
    border: 0; border-right: 1px solid #dde6ef;
    border-bottom: 1px solid #cfdbe6;
}}
QHeaderView::section:hover {{ background: #dfeefa; color: {C.BLUE_DEEP}; }}
QTableView QLineEdit, QTableView QComboBox {{
    border: 1px solid {C.BLUE}; border-radius: 0; padding: 0 4px;
    background: #fff; margin: 0;
}}

/* 输入类 */
QLineEdit, QComboBox, QDateEdit {{
    border: 1px solid #cfdce9; border-radius: 3px;
    height: 26px; padding: 0 7px; background: #fdfefe;
    selection-background-color: {C.BLUE};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {C.BLUE}; background: #fff; }}
QComboBox::drop-down {{ border: 0; width: 16px; }}
QComboBox QAbstractItemView {{
    border: 1px solid #cfdce9; background: #fff;
    selection-background-color: {C.BLUE_BG}; selection-color: {C.BLUE_DEEP};
}}

/* 状态条 */
QStatusBar {{
    background: #f7fafd; border-top: 1px solid {C.LINE};
    color: {C.TEXT3}; font-size: 11.5px;
}}
QStatusBar::item {{ border: 0; }}

/* 模式条 */
QLabel#modebar {{
    padding: 0 12px; min-height: 26px;
    background: {C.WARN_BG}; color: {C.WARN};
    border-bottom: 1px solid #f0e2c4;
}}
QLabel#modebar[editable="true"] {{
    background: {C.OK_BG}; color: {C.OK};
    border-bottom: 1px solid #cde3d2;
}}

/* 标记过滤 */
QWidget#tagbar {{ background: #fbfdff; border-bottom: 1px solid {C.LINE_SOFT}; }}
QPushButton#tagchip {{
    border: 1px solid #d5e2ee; border-radius: 11px;
    padding: 0 10px; height: 21px; background: #fff; color: #4a6274;
    font-size: 11.5px;
}}
QPushButton#tagchip:checked {{
    background: {C.BLUE_BG}; border-color: #8fbfe4;
    color: #14538a; font-weight: 700;
}}

QSplitter::handle {{ background: {C.LINE}; }}
QSplitter::handle:hover {{ background: #b9cadb; }}
QToolBar {{ border: 0; spacing: 4px; padding: 4px 8px; background: {C.PANEL}; }}
"""


# ============================================================ 数据模型 ===
class AwA_TableModel(QAbstractTableModel):
    """一个分类的表格数据。organize=False 时只读。"""

    GroupCol = 2          # 测点名所在列（固定前 7 列顺序）

    def __init__(self, store: core.Store, cat: str, organize: bool):
        super().__init__()
        self.store = store
        self.cat = cat
        self.organize = organize
        self.headers: list[tuple[str, int]] = []
        self.rows: list[list[str]] = []
        self.fields: list[dict] = []
        self.tag_filter = ""
        self.reload()

    # ---------- 数据装载 ----------
    def reload(self) -> None:
        data = self.store.table(self.cat, organize=self.organize,
                                tag_filter=self.tag_filter)
        self.beginResetModel()
        self.headers = data["headers"]
        self.rows = data["rows"]
        self.fields = data["fields"] or [{} for _ in self.rows]
        self.kind = data.get("kind", "")
        self.note = data.get("note", "")
        self.endResetModel()

    def set_tag_filter(self, tag: str) -> None:
        self.tag_filter = tag
        self.reload()

    # ---------- QAbstractTableModel ----------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return self.headers[section][0]
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignLeft | Qt.AlignVCenter)
        else:
            if role == Qt.DisplayRole:
                return str(section + 1)
        return None

    def field_at(self, row: int, col: int) -> dict:
        f = self.fields[row] if row < len(self.fields) else {}
        return f.get(col) or f.get(str(col)) or {}

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        val = self.rows[r][c] if c < len(self.rows[r]) else ""
        f = self.field_at(r, c)

        if role == Qt.DisplayRole:
            return "" if val == "—" else str(val)
        if role == Qt.EditRole:
            return "" if val == "—" else str(val)

        if role == Qt.TextAlignmentRole:
            if c >= 1 and self._is_num(val):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            if f.get("t") == "tag":
                return int(Qt.AlignCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)

        if role == Qt.BackgroundRole:
            # 标记列着色
            if f.get("t") == "tag" and val:
                return QBrush(QColor(C.NOISE_BG if val == "噪声级" else C.INSUL_BG))
            # 修改过的单元格
            if self.organize and self.store.edits.data.get(self.rows[r][1], {}).get(
                    f.get("p", "")) is not None:
                return QBrush(QColor(C.DURTY))
            return None

        if role == Qt.ForegroundRole:
            if f.get("t") == "tag" and val:
                return QBrush(QColor(C.WARN if val == "噪声级" else C.OK))
            if val == "—":
                return QBrush(QColor("#b9c4d0"))
            return None

        if role == Qt.FontRole:
            if f.get("t") == "tag" and val:
                fo = QFont("Microsoft YaHei UI", 9)
                fo.setBold(True)
                return fo
            return None

        if role == Qt.ToolTipRole:
            if f.get("ro"):
                return f"{val}　（仪器记录，只读）"
            if f.get("t") == "tag":
                return "单击选择：噪声级 / 隔声"
            if self.organize and f.get("p"):
                extra = "（改动同步到同编号的 4 个文件）" if f.get("one") else ""
                return f"{val}　单击修改，Tab 跳到下一格{extra}"
            return f"{val}　（原始数据只读）" if val else ""
        return None

    @staticmethod
    def _is_num(v) -> bool:
        try:
            float(str(v))
            return True
        except (TypeError, ValueError):
            return False

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if not self.organize:
            return base
        f = self.field_at(index.row(), index.column())
        if f and not f.get("ro") and f.get("p"):
            return base | Qt.ItemIsEditable
        return base

    # ---------- 编辑写入 ----------
    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        r, c = index.row(), index.column()
        f = self.field_at(r, c)
        if not f.get("p"):
            return False

        name = self.rows[r][1]
        text = ("" if value is None else str(value)).strip()
        try:
            self.store.update(name, f["p"], text)
        except ValueError as e:
            QMessageBox.warning(None, "无法保存", str(e))
            return False

        # 组联动：元数据同步到同编号的其他行
        gid = self.store.group_of(name)
        for i, row in enumerate(self.rows):
            if i == r:
                continue
            if f.get("one") == "group" and self.store.group_of(row[1]) == gid:
                row[c] = text
                top = self.index(i, c)
                self.dataChanged.emit(top, top)

        self.rows[r][c] = text
        self.dataChanged.emit(index, index)
        return True

    def refresh_row(self, r: int) -> None:
        if 0 <= r < len(self.rows):
            self.dataChanged.emit(self.index(r, 0),
                                  self.index(r, len(self.headers) - 1))

    # 供筛选代理取原始值
    def raw(self, r: int, c: int):
        return self.rows[r][c] if r < len(self.rows) else ""

    # ---------- 排序（模块内排序，保证行号与数据始终对应） ----------
    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
        if column < 0 or not self.rows:
            return

        def key(i):
            v = self.rows[i][column] if column < len(self.rows[i]) else ""
            s = "" if v == "—" else str(v)
            try:
                return (0, float(s), i)
            except ValueError:
                return (1, s, i)

        # 空值恒排末尾，不随升降序翻转
        blanks = [i for i in range(len(self.rows))
                  if not str(self.rows[i][column]).strip()
                  or str(self.rows[i][column]).strip() == "—"]
        data = [i for i in range(len(self.rows)) if i not in set(blanks)]

        self.layoutAboutToBeChanged()
        data.sort(key=key, reverse=(order == Qt.DescendingOrder))
        order_idx = data + blanks
        self.rows = [self.rows[i] for i in order_idx]
        self.fields = [self.fields[i] if i < len(self.fields) else {}
                       for i in order_idx]
        self.layoutChanged()


# ============================================================ 曲线画布 ===
class SpectrumCanvas(QWidget):
    """自绘频谱曲线：1/3OCT 33 点、OCT 11 点，支持勾选显示哪些统计量。"""

    METRICS = [
        ("Leq,T", "Leq,T", "#2b7fc4"),
        ("LFmax", "LFmax", "#c94a3a"),
        ("LFmin", "LFmin", "#3f8f5f"),
        ("LSmax", "LSmax", "#c98a2f"),
        ("LSmin", "LSmin", "#7a5ea8"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.rec = None
        self.vis = {k: True for k, _, _ in self.METRICS}
        self.hover = None
        self.setMouseTracking(True)

    def set_record(self, rec):
        self.rec = rec
        self.hover = None
        self.update()

    def set_visible(self, key: str, on: bool):
        self.vis[key] = on
        self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.fillRect(self.rect(), QColor("#fff"))

        kind = (self.rec or {}).get("kind", "")
        if self.rec is None:
            self._msg(p, "点击上方列表中的文件查看曲线")
            return
        if kind in ("1/3OCT", "OCT"):
            self._paint_spectrum(p)
        elif kind == "STA":
            self._paint_stats(p)
        elif kind == "NUM":
            self._paint_dist(p)
        else:
            self._msg(p, f"该类型（{kind or '未知'}）暂无图形预览")

    def _msg(self, p, text):
        p.setPen(QColor(C.TEXT3))
        p.drawText(self.rect(), Qt.AlignCenter, text)

    def _paint_spectrum(self, p):
        area = self.rect().adjusted(58, 18, -18, -40)
        bands = self._bands()
        if not bands:
            self._msg(p, "该文件没有频谱数据")
            return

        vals = []
        for key, _, _ in self.METRICS:
            if not self.vis[key]:
                continue
            m = self.rec["metrics"].get(key, {})
            vals += [v for v in m.values() if v is not None]
        if not vals:
            self._msg(p, "已隐藏全部曲线")
            return

        lo, hi, step = self._nice(min(vals), max(vals))
        self._grid(p, area, lo, hi, step, bands)
        self._curves(p, area, lo, hi, bands)
        if self.hover:
            self._marker(p, area, lo, hi, bands)

    # ---------- STA 统计柱状图 ----------
    STA_KEYS = [("LeqT", "Leq,T"), ("Lmax", "Lmax"), ("Lmin", "Lmin"),
                ("L 5", "L5"), ("L10", "L10"), ("L50", "L50"),
                ("L90", "L90"), ("L95", "L95"), ("SEL", "SEL")]

    def _stat_values(self):
        st = next(iter(self.rec.get("stats", {}).values()), {})
        return [(lbl, st.get(k)) for k, lbl in self.STA_KEYS if st.get(k) is not None]

    def _paint_stats(self, p):
        vals = self._stat_values()
        if not vals:
            self._msg(p, "该文件没有统计数据")
            return
        area = self.rect().adjusted(58, 18, -18, -40)
        nums = [v for _, v in vals]
        lo, hi, step = self._nice(min(nums), max(nums))
        lo = min(lo, min(nums) - 2)
        hi = max(hi, max(nums) + 2)

        # 网格与 Y 轴
        p.setPen(QPen(QColor("#eef3f8"), 1))
        v = lo
        while v <= hi + 1e-9:
            y = area.bottom() - (v - lo) / (hi - lo) * area.height()
            p.drawLine(area.left(), int(y), area.right(), int(y))
            v += step
        p.setPen(QColor(C.TEXT2))
        p.setFont(QFont("Consolas", 8))
        v = lo
        while v <= hi + 1e-9:
            y = area.bottom() - (v - lo) / (hi - lo) * area.height()
            p.drawText(2, int(y) - 8, 52, 16, Qt.AlignRight | Qt.AlignVCenter, f"{v:.0f}")
            v += step

        # 柱子
        n = len(vals)
        bw = area.width() / max(n, 1)
        color = QColor("#5b9bd5")
        for i, (lbl, v) in enumerate(vals):
            h = (v - lo) / (hi - lo) * area.height()
            x = area.left() + i * bw + bw * 0.18
            p.setBrush(QBrush(color))
            p.setPen(Qt.NoPen)
            p.drawRect(int(x), int(area.bottom() - h),
                       max(int(bw * 0.64), 3), int(h))
            # 数值
            p.setPen(QColor(C.TEXT2))
            p.setFont(QFont("Consolas", 7))
            p.drawText(int(x) - 4, int(area.bottom() - h) - 13,
                       int(bw), 12, Qt.AlignHCenter, f"{v:.1f}")
            # 标签
            p.setPen(QColor(C.TEXT3))
            p.setFont(QFont("Microsoft YaHei UI", 7))
            p.drawText(int(x) - 6, area.bottom() + 4, int(bw), 14,
                       Qt.AlignHCenter | Qt.AlignTop, lbl)
        p.setPen(QPen(QColor("#cfdbe6"), 1))
        p.drawLine(area.left(), area.bottom(), area.right(), area.bottom())
        p.drawLine(area.left(), area.top(), area.left(), area.bottom())

    # ---------- NUM 声级分布曲线 ----------
    def _paint_dist(self, p):
        pts = [(lv, pc) for lv, pc in (self.rec.get("dist") or []) if pc and pc > 0]
        if not pts:
            self._msg(p, "该文件没有有效的声级分布数据")
            return
        area = self.rect().adjusted(58, 18, -18, -40)
        lo, hi, step = self._nice(min(v for v, _ in pts), max(v for v, _ in pts))
        ymax = max(v for _, v in pts)

        # 网格
        p.setPen(QPen(QColor("#eef3f8"), 1))
        v = lo
        while v <= hi + 1e-9:
            x = area.left() + (v - lo) / (hi - lo) * area.width()
            p.drawLine(int(x), area.top(), int(x), area.bottom())
            v += step
        p.setPen(QColor(C.TEXT2))
        p.setFont(QFont("Consolas", 8))
        v = lo
        while v <= hi + 1e-9:
            x = area.left() + (v - lo) / (hi - lo) * area.width()
            p.drawText(int(x) - 20, area.bottom() + 4, 40, 14,
                       Qt.AlignHCenter | Qt.AlignTop, f"{v:.0f}")
            v += step
        # Y 轴（占比 %）
        p.drawText(2, area.top() - 4, 52, 14, Qt.AlignLeft, f"{ymax:.0f}%")

        def xy(lv, pc):
            x = area.left() + (lv - lo) / (hi - lo) * area.width()
            y = area.bottom() - pc / ymax * area.height()
            return x, y

        p.setPen(QPen(QColor("#2b7fc4"), 1.6))
        prev = None
        for lv, pc in pts:
            x, y = xy(lv, pc)
            if prev:
                p.drawLine(int(prev[0]), int(prev[1]), int(x), int(y))
            prev = (x, y)
        p.setBrush(QBrush(QColor("#2b7fc4")))
        p.setPen(Qt.NoPen)
        for lv, pc in pts:
            x, y = xy(lv, pc)
            p.drawRect(int(x) - 1, int(y) - 1, 3, 3)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#cfdbe6"), 1))
        p.drawLine(area.left(), area.bottom(), area.right(), area.bottom())
        p.drawLine(area.left(), area.top(), area.left(), area.bottom())

    def _bands(self) -> list[str]:
        if not self.rec:
            return []
        m = self.rec["metrics"].get("Leq,T") or {}
        return sorted(m.keys(), key=float)

    @staticmethod
    def _nice(lo: float, hi: float):
        span = max(hi - lo, 1e-6)
        raw = span / 6.0
        mag = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 1
        for m in (1, 2, 5, 10):
            if raw <= m * mag:
                step = m * mag
                break
        else:
            step = 10 * mag
        lo2 = (int(lo / step)) * step - step
        hi2 = (int(hi / step) + 2) * step
        return lo2, hi2, step

    def _grid(self, p, a, lo, hi, step, bands):
        p.setPen(QPen(QColor("#eef3f8"), 1))
        v = lo
        while v <= hi + 1e-9:
            y = a.bottom() - (v - lo) / (hi - lo) * a.height()
            p.drawLine(a.left(), int(y), a.right(), int(y))
            v += step
        # Y 轴刻度
        p.setPen(QColor(C.TEXT2))
        f = QFont("Consolas", 8)
        p.setFont(f)
        v = lo
        while v <= hi + 1e-9:
            y = a.bottom() - (v - lo) / (hi - lo) * a.height()
            p.drawText(2, int(y) - 8, 52, 16, Qt.AlignRight | Qt.AlignVCenter,
                       f"{v:.0f}")
            v += step
        # X 轴频带标签
        n = len(bands)
        p.setPen(QColor(C.TEXT3))
        for i, b in enumerate(bands):
            x = a.left() + (a.width() * i / (n - 1) if n > 1 else a.width() / 2)
            if n <= 12 or i % 3 == 0:
                p.drawText(int(x) - 22, a.bottom() + 4, 44, 14,
                           Qt.AlignHCenter | Qt.AlignTop,
                           core.band_label(b))
        p.setPen(QPen(QColor("#cfdbe6"), 1))
        p.drawLine(a.left(), a.bottom(), a.right(), a.bottom())
        p.drawLine(a.left(), a.top(), a.left(), a.bottom())

    def _xy(self, a, lo, hi, bands, i, v):
        n = len(bands)
        x = a.left() + (a.width() * i / (n - 1) if n > 1 else a.width() / 2)
        y = a.bottom() - (v - lo) / (hi - lo) * a.height()
        return x, y

    def _curves(self, p, a, lo, hi, bands):
        for key, _, color in self.METRICS:
            if not self.vis[key]:
                continue
            m = self.rec["metrics"].get(key, {})
            pts = [(i, b, m.get(b)) for i, b in enumerate(bands)
                   if m.get(b) is not None]
            if not pts:
                continue
            p.setPen(QPen(QColor(color), 1.6))
            prev = None
            for i, b, v in pts:
                x, y = self._xy(a, lo, hi, bands, i, v)
                if prev:
                    p.drawLine(int(prev[0]), int(prev[1]), int(x), int(y))
                prev = (x, y)
            if len(bands) <= 40:
                p.setBrush(QBrush(QColor(color)))
                p.setPen(Qt.NoPen)
                for i, b, v in pts:
                    x, y = self._xy(a, lo, hi, bands, i, v)
                    p.drawRect(int(x) - 1, int(y) - 1, 3, 3)
                p.setBrush(Qt.NoBrush)

    def _marker(self, p, a, lo, hi, bands):
        i, b, v, color = self.hover
        x, y = self._xy(a, lo, hi, bands, i, v)
        p.setPen(QPen(QColor("#e05a3a"), 1.4))
        p.drawEllipse(int(x) - 4, int(y) - 4, 8, 8)
        p.setPen(QColor("#e05a3a"))
        p.setFont(QFont("Consolas", 8))
        p.drawText(int(x) + 8, int(y) - 16,
                   f"{core.band_label(b)}  {v:.1f} dB")

    # ---------- 鼠标 ----------
    def mouseMoveEvent(self, ev):
        if not self.rec or self.rec.get("kind") not in ("1/3OCT", "OCT"):
            return
        bands = self._bands()
        if not bands:
            return
        a = self.rect().adjusted(58, 18, -18, -40)
        vals = []
        for key, _, _ in self.METRICS:
            if self.vis[key]:
                vals += [v for v in self.rec["metrics"].get(key, {}).values()
                         if v is not None]
        lo, hi, _ = self._nice(min(vals), max(vals))
        mx, my = ev.position().x(), ev.position().y()

        best, best_d = None, 14
        for key, _, color in self.METRICS:
            if not self.vis[key]:
                continue
            m = self.rec["metrics"].get(key, {})
            for i, b in enumerate(bands):
                v = m.get(b)
                if v is None:
                    continue
                x, y = self._xy(a, lo, hi, bands, i, v)
                d = ((x - mx) ** 2 + (y - my) ** 2) ** 0.5
                if d < best_d:
                    best_d = d
                    best = (i, b, v, color)
        if best != self.hover:
            self.hover = best
            self.setCursor(Qt.PointingHandCursor if best else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, ev):
        self.hover = None
        self.update()


# ============================================================ 主窗口 ===
class MainWindow(QMainWindow):
    def __init__(self, store: core.Store):
        super().__init__()
        self.store = store
        self.cat = "13OCT"
        self.organize = False
        self.module = "data"
        self.model: AwA_TableModel | None = None
        self.selected_file = ""
        self.detail_cache: dict[str, dict] = {}

        self.setWindowTitle("AWA 数据管理")
        self.setWindowIcon(self._make_icon())
        self.resize(1440, 880)

        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_modbar())
        self.modebar = QLabel(objectName="modebar")
        outer.addWidget(self.modebar)
        outer.addWidget(self._build_tagbar())

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_sidebar())
        split.addWidget(self._build_content())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([230, 1200])
        outer.addWidget(split, 1)

        self.setStatusBar(QStatusBar())
        self._apply_mode()
        self.mod_buttons["data"].setChecked(True)

    # ---------- 图标 ----------
    @staticmethod
    def _make_icon() -> QIcon:
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(C.BLUE)))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(2, 2, 60, 60, 12, 12)
        p.setPen(QPen(QColor("#fff"), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        pts = [(14, 44), (24, 30), (34, 38), (50, 18)]
        for i in range(len(pts) - 1):
            p.drawLine(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        p.end()
        return QIcon(pm)

    # ---------- 顶部模块栏 ----------
    def _build_modbar(self) -> QWidget:
        w = QWidget(objectName="modbar")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 0, 12, 0)
        lay.setSpacing(0)

        self.mod_buttons = {}
        for key, label in (("data", "数据管理"), ("organize", "数据整理"),
                           ("report", "报告生成")):
            b = QPushButton(label, objectName="modbtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set_module(k))
            lay.addWidget(b)
            self.mod_buttons[key] = b
        for label in ("基本信息", "图标管理", "实时监测", "模板管理"):
            b = QPushButton(label, objectName="modbtn")
            b.setEnabled(False)
            lay.addWidget(b)

        lay.addStretch(1)

        self.badge = QLabel("原始数据")
        self.badge.setStyleSheet(
            f"background:{C.BLUE_BG}; color:{C.BLUE_DEEP}; border-radius:9px;"
            f"padding:2px 10px; font-size:11px; font-weight:700;")
        lay.addWidget(self.badge)

        btn_dir = QPushButton("切换数据目录", objectName="act")
        btn_dir.setCursor(Qt.PointingHandCursor)
        btn_dir.clicked.connect(self.choose_dir)
        lay.addSpacing(10)
        lay.addWidget(btn_dir)

        btn_read = QPushButton("重新读取", objectName="act", )
        btn_read.setProperty("primary", True)
        btn_read.setCursor(Qt.PointingHandCursor)
        btn_read.clicked.connect(self.rescan)
        lay.addSpacing(6)
        lay.addWidget(btn_read)
        return w

    # ---------- 侧栏 ----------
    def _build_sidebar(self) -> QWidget:
        from PySide6.QtWidgets import QListWidget, QListWidgetItem

        w = QWidget(objectName="sidebar")
        w.setFixedWidth(232)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QLabel("数据分类", objectName="sidehead")
        lay.addWidget(head)

        self.catlist = QListWidget(objectName="catlist")
        self.catlist.setCursor(Qt.PointingHandCursor)
        self.catlist.itemClicked.connect(self._on_cat_clicked)
        lay.addWidget(self.catlist, 1)

        foot = QWidget()
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(12, 8, 12, 10)
        fl.setSpacing(3)
        for key, label in (("insModel", "仪器"), ("insSerial", "编号"),
                           ("insRange", "量程")):
            row = QHBoxLayout()
            row.setSpacing(4)
            lb = QLabel(label)
            lb.setStyleSheet(f"color:{C.TEXT3}; font-size:11px;")
            vl = QLabel("—")
            vl.setStyleSheet("font-size:11px; font-weight:700; color:#3a6b91;")
            setattr(self, key, vl)
            row.addWidget(lb)
            row.addStretch(1)
            row.addWidget(vl)
            fl.addLayout(row)
        lay.addWidget(foot)
        return w

    # ---------- 右侧内容 ----------
    def _build_content(self) -> QWidget:
        from PySide6.QtWidgets import QStackedWidget

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_data_page())

        from report_ui import ReportPage
        self.report_page = ReportPage(self.store)
        self.stack.addWidget(self.report_page)
        return self.stack

    def _build_data_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 分类说明行
        self.note = QLabel("")
        self.note.setStyleSheet(
            f"padding:4px 12px; color:{C.TEXT3}; font-size:11.5px;"
            f"background:{C.PANEL}; border-bottom:1px solid {C.LINE_SOFT};")
        lay.addWidget(self.note)

        # 表格
        self.view = QTableView()
        self.view.setSortingEnabled(True)
        self.view.horizontalHeader().setSortIndicatorShown(True)
        self.view.setAlternatingRowColors(False)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setWordWrap(False)
        self.view.horizontalHeader().setHighlightSections(False)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.view.verticalHeader().setDefaultSectionSize(24)
        self.view.verticalHeader().setVisible(False)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.clicked.connect(self._on_cell_clicked)
        lay.addWidget(self.view, 3)

        # 曲线工具行（仅频谱类型有意义，其他类型隐藏）
        self.curvebar = QWidget()
        bl = QHBoxLayout(self.curvebar)
        bl.setContentsMargins(10, 4, 10, 4)
        bl.setSpacing(10)
        bl.addWidget(QLabel("曲线"))
        self.curve_checks = {}
        for key, label, color in SpectrumCanvas.METRICS:
            from PySide6.QtWidgets import QCheckBox
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.setStyleSheet(f"QCheckBox{{spacing:4px;color:{color};font-size:11.5px;}}")
            cb.toggled.connect(lambda on, k=key: self.canvas.set_visible(k, on))
            bl.addWidget(cb)
            self.curve_checks[key] = cb
        bl.addStretch(1)
        self.curve_title = QLabel("—")
        self.curve_title.setStyleSheet(f"color:{C.TEXT3};font-size:11.5px;")
        bl.addWidget(self.curve_title)
        self.curvebar.setStyleSheet(
            f"background:{C.PANEL}; border-top:1px solid {C.LINE};"
            f"border-bottom:1px solid {C.LINE_SOFT};")
        lay.addWidget(self.curvebar)

        self.canvas = SpectrumCanvas()
        lay.addWidget(self.canvas, 2)
        return w

    def _build_tagbar(self) -> QWidget:
        w = QWidget(objectName="tagbar")
        w.setFixedHeight(32)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(6)

        lb = QLabel("显示")
        lb.setStyleSheet(f"color:{C.TEXT3};font-size:11.5px;")
        lay.addWidget(lb)

        self.tag_chips = {}
        for key, label in (("", "全部"), ("噪声级", "噪声级"), ("隔声", "隔声")):
            b = QPushButton(label, objectName="tagchip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set_tag_filter(k))
            lay.addWidget(b)
            self.tag_chips[key] = b
        self.tag_chips[""].setChecked(True)

        lay.addStretch(1)
        self.tag_hint = QLabel("")
        self.tag_hint.setStyleSheet(f"color:{C.TEXT3};font-size:11px;")
        lay.addWidget(self.tag_hint)
        self.tagbar = w
        return w

    # ---------- 模块切换 ----------
    def set_module(self, key: str) -> None:
        self.module = key
        self.organize = (key == "organize")
        for k, b in self.mod_buttons.items():
            b.setChecked(k == key)

        if key == "report":
            self.stack.setCurrentWidget(self.report_page)
            self._apply_mode()
            self.report_page.set_store(self.store)
            return

        self.stack.setCurrentIndex(0)
        self._apply_mode()
        self.reload_table()

    def _apply_mode(self) -> None:
        if self.module == "report":
            self.badge.setText("报告生成")
            self.modebar.setText(
                "  报告生成 · 左侧是测点清单，右侧填内侧/外侧文件与设计值，"
                "曲线即时预览；点【生成表格与曲线】输出报告用的 xlsx 和图")
            self.modebar.setProperty("editable", False)
            self.tagbar.setVisible(False)
            self.modebar.style().unpolish(self.modebar)
            self.modebar.style().polish(self.modebar)
            return

        self.tagbar.setVisible(not self.organize)
        if self.organize:
            self.badge.setText("数据整理")
            self.modebar.setText(
                "  数据整理 · 单击单元格可修改，Tab 跳到下一格；"
                "改动只记在本目录的 .awa-edits.json，原始 AWA 文件不会被改写")
            self.modebar.setProperty("editable", True)
            self.view.setEditTriggers(
                QAbstractItemView.DoubleClicked |
                QAbstractItemView.SelectedClicked |
                QAbstractItemView.EditKeyPressed)
            self.tagbar.setVisible(True)
        else:
            self.badge.setText("原始数据")
            self.modebar.setText(
                "  原始数据只读 · 仪器导出的 AWA 原样展示，不参与任何整理与计算；"
                "如需修改请切换到【数据整理】")
            self.modebar.setProperty("editable", False)
            self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.tagbar.setVisible(False)
        self.modebar.style().unpolish(self.modebar)
        self.modebar.style().polish(self.modebar)

    # ---------- 数据加载 ----------
    def rescan(self, allow_pick: bool = True) -> None:
        try:
            info = self.store.scan(self.store.dir)
        except ValueError as e:
            # 目录无效时引导用户选择，而不是只报错
            # （打包后首次启动极易遇到：配置在临时目录里找不到）
            if allow_pick:
                QMessageBox.warning(
                    self, "需要选择数据目录",
                    f"{e}\n\n现在选择本次测试数据所在的文件夹。")
                self.choose_dir()
            else:
                QMessageBox.critical(self, "读取失败", str(e))
            return
        self.detail_cache.clear()
        self._fill_categories(info)
        self._fill_instrument(info.get("instrument") or {})
        self.reload_table()
        if self.module == "report":
            self.report_page.set_store(self.store)
        self.statusBar().showMessage(
            f"{info['dir']}　共 {info['files']} 个 AWA 文件　"
            f"用时 {info['elapsedMs']} ms", 8000)

    def choose_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择本次测试数据所在的文件夹",
                                             self.store.dir)
        if not d:
            return
        self.store.dir = os.path.abspath(d)
        self.rescan()

    def _fill_categories(self, info: dict) -> None:
        from PySide6.QtWidgets import QListWidgetItem
        self.catlist.clear()
        for c in info.get("categories", []):
            n = c.get("count", 0)
            item = QListWidgetItem(f"{c['label']}　{n}")
            item.setData(Qt.UserRole, c["key"])
            if n == 0:
                item.setForeground(QBrush(QColor("#b0bcc8")))
            self.catlist.addItem(item)
            if c["key"] == self.cat:
                self.catlist.setCurrentItem(item)

    def _fill_instrument(self, ins: dict) -> None:
        self.insModel.setText(ins.get("model") or "—")
        self.insSerial.setText(ins.get("serial") or "—")
        self.insRange.setText(ins.get("range") or "—")

    def _on_cat_clicked(self, item) -> None:
        key = item.data(Qt.UserRole)
        if key:
            self.cat = key
            self.reload_table()

    def reload_table(self) -> None:
        prev_file = self.selected_file
        self.model = AwA_TableModel(self.store, self.cat, self.organize)
        self.model.set_tag_filter(self._current_tag())

        self.view.setModel(self.model)
        self.view.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive)
        for i, (_, w) in enumerate(self.model.headers):
            self.view.setColumnWidth(i, w)
        self.view.setColumnWidth(0, 52)
        self.view.setColumnWidth(1, 152)

        self.note.setText(self.model.note)
        self._update_tag_chips()
        self.selected_file = ""
        self.canvas.set_record(None)
        self.curve_title.setText("—")

        if self.model.rows:
            self.view.selectRow(0)
            self._select_file(self.model.rows[0][1])

    # ---------- 标记 ----------
    def _current_tag(self) -> str:
        for k, b in self.tag_chips.items():
            if b.isChecked():
                return k
        return ""

    def set_tag_filter(self, key: str) -> None:
        for k, b in self.tag_chips.items():
            b.setChecked(k == key)
        self.reload_table()

    def _update_tag_chips(self) -> None:
        counts = self.store.tag_counts(self.cat)
        total = sum(counts.values())
        labels = {"": "全部", "噪声级": "噪声级", "隔声": "隔声"}
        for k, b in self.tag_chips.items():
            n = total if k == "" else counts.get(k, 0)
            b.setText(f"{labels[k]}  {n}")
        cur = self._current_tag()
        if cur:
            self.tag_hint.setText(f"当前只显示「{cur}」，共 {counts.get(cur, 0)} 组")
        else:
            self.tag_hint.setText(f"当前显示全部 {total} 组")

    # ---------- 单元格与曲线 ----------
    def _on_cell_clicked(self, index) -> None:
        row = index.row()
        if row >= len(self.model.rows):
            return
        self._select_file(self.model.rows[row][1])

    def _select_file(self, name: str) -> None:
        self.selected_file = name
        rec = self.detail_cache.get(name)
        if rec is None:
            rec = self.store.detail(name, organize=self.organize)
            if rec is None:
                return
            self.detail_cache[name] = rec
        # 曲线显示开关只对频谱类有意义；STA/NUM 有自己的图形
        self.curvebar.setVisible(rec.get("kind") in ("1/3OCT", "OCT"))
        self.curve_title.setText(
            f"{name}　{rec.get('point', '')}　{rec.get('date', '')} {rec.get('time', '')}")
        self.canvas.set_record(rec)


# ============================================================ 入口 ===
def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="AWA 数据管理（桌面版）")
    ap.add_argument("--dir", default="", help="数据目录")
    args = ap.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("AWA 数据管理")
    app.setStyleSheet(STYLE)

    root = args.dir or core.ROOT_DEFAULT
    store = core.Store(root)
    win = MainWindow(store)
    win.show()
    win.rescan()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
