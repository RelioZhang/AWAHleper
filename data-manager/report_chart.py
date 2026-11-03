#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AWA 报告生成 · 曲线绘制
=================================================
一张 1/3 倍频程隔声曲线，预览和导出共用同一套绘制代码，保证所见即所得。

图形要素（对齐报告里的 图 3.2-1 风格）：
  · 蓝色折线 + 方点   —— 实测声压级差 NR
  · 红色虚线          —— NIC 评价轮廓（只在 125Hz~4kHz 有定义）
  · 浅红色竖条        —— 不利偏差（轮廓高于实测的频带），即扣分处
  · 白底、浅灰网格、对数频率轴
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPen,
                           QPolygonF)


# ---------------------------------------------------------------- 配色 ---
BG = "#ffffff"
GRID = "#eef3f8"
AXIS = "#cfdbe6"
TEXT = "#5b6b7b"
TEXT2 = "#94a3b3"
NR_COLOR = "#2b7fc4"
CONTOUR_COLOR = "#c94a3a"
DEFICIT_FILL = QColor(201, 74, 58, 40)
DEFICIT_EDGE = QColor(201, 74, 58, 90)

# 报告图的 X 轴标注位置（不再密集标全部频带）
X_LABELS = [100, 200, 400, 800, 1600, 3150, 5000]


def _label(hz: int) -> str:
    if hz >= 1000:
        return f"{hz / 1000:.4f}".rstrip("0").rstrip(".") + "k"
    return str(hz)


class ChartData:
    """一张隔声图需要的全部数据。"""

    def __init__(self, bands, values, nic=None, title="", subtitle=""):
        self.bands = list(bands)            # [100, 125, ...]
        self.values = list(values)          # 与 bands 等长
        self.nic = nic
        self.title = title
        self.subtitle = subtitle


# ---------------------------------------------------------------- 绘制 ---
def draw_chart(p: QPainter, rect: QRectF, data: ChartData,
               show_legend: bool = True, base_pt: float = 9.0) -> None:
    """在 rect 内画一张隔声曲线。调用方负责背景与缩放。"""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)

    f_axis = QFont("Microsoft YaHei UI")
    f_axis.setPointSizeF(base_pt)
    f_tick = QFont("Consolas")
    f_tick.setPointSizeF(base_pt - 0.5)
    f_title = QFont("Microsoft YaHei UI")
    f_title.setPointSizeF(base_pt + 1.5)
    f_title.setBold(True)

    top = rect.top()
    if data.title:
        p.setFont(f_title)
        p.setPen(QColor(TEXT))
        p.drawText(QRectF(rect.left(), top, rect.width(), base_pt * 2.2),
                   Qt.AlignHCenter | Qt.AlignVCenter, data.title)
        top += base_pt * 2.4

    legend_h = base_pt * 2.0 if show_legend else 0
    area = QRectF(rect.left() + base_pt * 5.2, top,
                  rect.width() - base_pt * 6.0,
                  rect.bottom() - top - base_pt * 3.6 - legend_h)
    if area.width() < 40 or area.height() < 40:
        p.restore()
        return

    # ---- 取值范围 ----
    vals = [v for v in data.values if v is not None]
    contour = _contour_points(data)
    if contour:
        vals += [v for _, v in contour]
    if not vals:
        p.restore()
        return
    lo = min(vals)
    hi = max(vals)
    pad = max(3.0, (hi - lo) * 0.12)
    lo = math.floor((lo - pad) / 5.0) * 5.0
    hi = math.ceil((hi + pad) / 5.0) * 5.0
    if hi - lo < 10:
        hi = lo + 10

    f0, f1 = math.log10(data.bands[0]), math.log10(data.bands[-1])

    def px(hz: float) -> float:
        return area.left() + (math.log10(hz) - f0) / (f1 - f0) * area.width()

    def py(v: float) -> float:
        return area.bottom() - (v - lo) / (hi - lo) * area.height()

    # ---- 网格 ----
    p.setPen(QPen(QColor(GRID), 1))
    v = lo
    while v <= hi + 1e-9:
        y = py(v)
        p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        v += 5.0
    for hz in data.bands:                       # 竖向网格太密，只画标注位
        if hz in X_LABELS:
            x = px(hz)
            p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))

    # ---- 坐标轴 ----
    p.setPen(QPen(QColor(AXIS), 1))
    p.drawLine(area.bottomLeft(), area.bottomRight())
    p.drawLine(area.topLeft(), area.bottomLeft())

    # ---- 不利偏差阴影 ----
    if data.nic is not None:
        p.setPen(QPen(DEFICIT_EDGE, 0.8))
        p.setBrush(QBrush(DEFICIT_FILL))
        for hz, v_meas, v_cont in zip(data.bands, data.values, _contour_series(data)):
            if v_cont is None or v_meas is None:
                continue
            if v_cont > v_meas:                 # 轮廓在实测之上 = 这一格没达标
                half = (area.width() / (len(data.bands) - 1)) * 0.34
                x = px(hz)
                r = QRectF(x - half, py(v_cont), half * 2,
                           max(1.0, py(v_meas) - py(v_cont)))
                p.drawRect(r)
        p.setBrush(Qt.NoBrush)

    # ---- NIC 轮廓 ----
    if contour:
        pen = QPen(QColor(CONTOUR_COLOR), 1.3)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        poly = QPolygonF([QPointF(px(hz), py(v)) for hz, v in contour])
        p.drawPolyline(poly)

    # ---- 实测 NR ----
    p.setPen(QPen(QColor(NR_COLOR), 1.6))
    pts = [(px(hz), py(v)) for hz, v in zip(data.bands, data.values)
           if v is not None]
    if len(pts) > 1:
        p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))
    p.setBrush(QBrush(QColor(NR_COLOR)))
    p.setPen(Qt.NoPen)
    for x, y in pts:
        p.drawRect(QRectF(x - 1.6, y - 1.6, 3.2, 3.2))
    p.setBrush(Qt.NoBrush)

    # ---- 刻度文字 ----
    p.setFont(f_tick)
    p.setPen(QColor(TEXT2))
    v = lo
    while v <= hi + 1e-9:
        p.drawText(QRectF(rect.left(), py(v) - 8, base_pt * 4.4, 16),
                   Qt.AlignRight | Qt.AlignVCenter, f"{v:.0f}")
        v += 5.0
    for hz in X_LABELS:
        if data.bands[0] <= hz <= data.bands[-1]:
            p.drawText(QRectF(px(hz) - 26, area.bottom() + 4, 52,
                              base_pt * 1.6),
                       Qt.AlignHCenter | Qt.AlignTop, _label(hz))

    p.setFont(f_axis)
    p.setPen(QColor(TEXT))
    p.drawText(QRectF(area.left(), area.bottom() + base_pt * 1.8,
                      area.width(), base_pt * 1.6),
               Qt.AlignHCenter | Qt.AlignTop, "Frequency, Hz")

    # ---- 图例 ----
    if show_legend:
        y = rect.bottom() - legend_h + base_pt * 0.4
        x = area.left()
        p.setFont(f_axis)

        p.setPen(QPen(QColor(CONTOUR_COLOR), 1.3, Qt.DashLine))
        p.drawLine(QPointF(x, y + 6), QPointF(x + 16, y + 6))
        p.setPen(QColor(TEXT))
        p.drawText(QRectF(x + 20, y - 3, 60, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   "NIC contour")
        x += 92

        p.setPen(QPen(QColor(NR_COLOR), 1.6))
        p.drawLine(QPointF(x, y + 6), QPointF(x + 16, y + 6))
        p.setPen(QColor(TEXT))
        p.drawText(QRectF(x + 20, y - 3, 40, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   "NR")
        x += 52

        p.setPen(QPen(DEFICIT_EDGE, 0.8))
        p.setBrush(QBrush(DEFICIT_FILL))
        p.drawRect(QRectF(x, y + 1, 10, 10))
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(TEXT))
        p.drawText(QRectF(x + 16, y - 3, 70, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   "Deficiency")

        if data.nic is not None:
            nic_txt = (f"NIC-{data.nic}" if data.nic >= 0
                       else f"NIC({data.nic})")
            p.setFont(f_title)
            p.setPen(QColor(TEXT))
            p.drawText(QRectF(area.right() - 90, y - 4, 90, 20),
                       Qt.AlignRight | Qt.AlignVCenter, nic_txt)

    p.restore()


def _contour_series(data):
    """18 个频带上逐个给出轮廓值（125~4k 之外为 None）。"""
    from report import BANDS_THIRD, NIC_CONTOUR
    if data.nic is None:
        return [None] * len(data.bands)
    out = []
    for hz in data.bands:
        if hz in BANDS_THIRD:
            i = BANDS_THIRD.index(hz)
            out.append(NIC_CONTOUR[i - 1] + data.nic if 1 <= i <= 16 else None)
        else:
            out.append(None)
    return out


def _contour_points(data):
    return [(hz, v) for hz, v in zip(data.bands, _contour_series(data))
            if v is not None]


# ---------------------------------------------------------------- 导出 ---
def render_png(data: ChartData, path: str, width: int = 1200,
               height: int = 720, scale: int = 2) -> str:
    """导出 PNG。scale=2 相当于 2 倍图，贴进 Word 缩到 11cm 宽仍然清晰。"""
    img = QImage(width * scale, height * scale, QImage.Format_ARGB32)
    img.setDevicePixelRatio(scale)
    img.fill(QColor(BG))
    p = QPainter(img)
    p.scale(scale, scale)
    draw_chart(p, QRectF(0, 0, width, height), data, show_legend=True,
               base_pt=10.0)
    p.end()
    if not img.save(path, "PNG"):
        raise IOError(f"图片写入失败：{path}")
    return path


def render_svg(data: ChartData, path: str, width: int = 1200,
               height: int = 720) -> str:
    """导出 SVG（矢量，插进 Word 放大不虚）。"""
    from PySide6.QtSvg import QSvgGenerator
    gen = QSvgGenerator()
    gen.setFileName(path)
    gen.setSize(QSize(width, height))
    gen.setViewBox(QRect(0, 0, width, height))
    gen.setTitle(data.title or "NR")
    gen.setDescription("AWA report chart")
    p = QPainter(gen)
    p.fillRect(0, 0, width, height, QColor(BG))
    draw_chart(p, QRectF(0, 0, width, height), data, show_legend=True,
               base_pt=10.0)
    p.end()
    return path
