#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AWA 报告生成 · 界面页
=================================================
左边「测点清单」一句话一行，右边填这一个测点的信息并即时预览曲线，
点【生成】落盘：一个 xlsx（三张报告表）+ 每个隔声测点一张曲线图。

清单跟着数据目录走（.report-plan.json），换项目就是换目录，不用重填。
"""

from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox,
                               QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

import report as R
import report_chart as RC


# 与主界面同一套配色
BLUE = "#2b7fc4"
BLUE_DEEP = "#1b5f98"
TEXT = "#2b3947"
TEXT2 = "#5b6b7b"
TEXT3 = "#94a3b3"
LINE = "#dbe5ef"
PANEL = "#ffffff"
WARN = "#a8700f"
BAD = "#b8413a"
GOOD = "#2c6b48"


class NrPreview(QWidget):
    """隔声曲线预览，和导出的 PNG 用同一个绘制函数。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = None
        self.hint = "在左侧清单里选一个测点"
        self.setMinimumHeight(180)

    def set_data(self, data, hint=""):
        self.data = data
        self.hint = hint
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#fff"))
        if self.data is None:
            p.setPen(QColor(TEXT3))
            f = QFont("Microsoft YaHei UI")
            f.setPointSizeF(10)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, self.hint)
            p.end()
            return
        RC.draw_chart(p, QRectF(0, 0, self.width(), self.height()),
                      self.data, show_legend=True, base_pt=9.0)
        p.end()


class ReportPage(QWidget):
    COLUMNS = ("#", "测点名称", "类型", "内侧 / 文件", "外侧文件", "实测值", "判定")

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.items: list[R.Item] = []
        self.results: list[R.Result] = []
        self.cur = -1
        self._loading = False

        self._build()
        self.refresh()

    # ------------------------------------------------------------ 构建 ---
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_bar())

        body = QHBoxLayout()
        body.setContentsMargins(10, 8, 10, 8)
        body.setSpacing(10)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.itemSelectionChanged.connect(self._on_select)
        body.addWidget(self.table, 3)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        panel = QWidget()
        panel.setStyleSheet(f"background:{PANEL};border:1px solid {LINE};"
                            f"border-radius:4px;")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(10, 10, 10, 10)
        pl.setSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(7)

        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("如：0806 入户门")
        self.ed_name.editingFinished.connect(self._apply_form)

        self.cb_kind = QComboBox()
        self.cb_kind.addItems([R.KIND_INSUL, R.KIND_NOISE])
        self.cb_kind.currentIndexChanged.connect(self._apply_form)

        self.ed_table = QLineEdit()
        self.ed_table.setPlaceholderText("如：3.2-1")
        self.ed_table.editingFinished.connect(self._apply_form)

        self.cb_inner = QComboBox()
        self.cb_outer = QComboBox()
        self.cb_inner.currentIndexChanged.connect(self._apply_form)
        self.cb_outer.currentIndexChanged.connect(self._apply_form)

        self.ed_design = QLineEdit()
        self.ed_design.setPlaceholderText("如：NIC-28+ / NC-30")
        self.ed_design.editingFinished.connect(self._apply_form)

        form.addRow("名称", self.ed_name)
        form.addRow("类型", self.cb_kind)
        form.addRow("表号", self.ed_table)
        self.row_inner = form.rowCount()
        form.addRow("内侧 / 文件", self.cb_inner)
        self.row_outer = form.rowCount()
        form.addRow("外侧文件", self.cb_outer)
        form.addRow("设计值", self.ed_design)
        pl.addLayout(form)

        self.lb_result = QLabel("—")
        self.lb_result.setStyleSheet(
            f"color:{BLUE_DEEP};font-size:13px;font-weight:700;")
        self.lb_result.setTextInteractionFlags(Qt.TextSelectableByMouse)

        resrow = QHBoxLayout()
        resrow.setContentsMargins(0, 0, 0, 0)
        resrow.setSpacing(8)
        resrow.addWidget(self.lb_result, 1)
        self.btn_copy = QPushButton("复制数据", objectName="act")
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.setToolTip("按 Tab 分隔复制这张表，可直接粘到 Word / Excel")
        self.btn_copy.clicked.connect(self.copy_values)
        resrow.addWidget(self.btn_copy)
        pl.addLayout(resrow)

        self.lb_note = QLabel("")
        self.lb_note.setWordWrap(True)
        self.lb_note.setStyleSheet(f"color:{TEXT3};font-size:11.5px;")
        pl.addWidget(self.lb_note)

        # 频带明细：报告要把这些数抄进表 3.2-x / 表 3.3-x，不能只给一个评级
        self.nr_table = QTableWidget(0, 4)
        self.nr_table.verticalHeader().setVisible(False)
        self.nr_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.nr_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.nr_table.setWordWrap(False)
        self.nr_table.horizontalHeader().setHighlightSections(False)
        self.nr_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.nr_table.verticalHeader().setDefaultSectionSize(19)
        self.nr_table.setFixedHeight(196)
        self.nr_table.setStyleSheet(
            f"QTableWidget{{background:#fff;border:1px solid {LINE};"
            f"gridline-color:#eef3f8;font-size:11.5px;}}")
        pl.addWidget(self.nr_table)

        rl.addWidget(panel)
        self.preview = NrPreview()
        rl.addWidget(self.preview, 1)
        body.addWidget(right, 2)

        holder = QWidget()
        holder.setLayout(body)
        root.addWidget(holder, 1)

    def _build_bar(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background:{PANEL};border-bottom:1px solid {LINE};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(6)

        def act(text, slot, primary=False, danger=False):
            b = QPushButton(text, objectName="act")
            b.setCursor(Qt.PointingHandCursor)
            if primary:
                b.setProperty("primary", True)
            if danger:
                b.setProperty("danger", True)
            b.clicked.connect(slot)
            lay.addWidget(b)
            return b

        act("添加测点", self.add_item)
        act("删除", self.remove_item, danger=True)
        act("按时间配对", self.auto_pair)
        lay.addSpacing(14)

        lay.addWidget(QLabel("项目名称"))
        self.ed_project = QLineEdit("样板房声学测试报告")
        self.ed_project.setFixedWidth(220)
        lay.addWidget(self.ed_project)

        lay.addStretch(1)
        self.lb_hint = QLabel("")
        self.lb_hint.setStyleSheet(f"color:{TEXT3};font-size:11.5px;")
        lay.addWidget(self.lb_hint)
        act("生成表格与曲线", self.generate, primary=True)
        return w

    # ------------------------------------------------------------ 数据 ---
    def set_store(self, store):
        self.store = store
        for cb in (self.cb_inner, self.cb_outer):
            cb.blockSignals(True)
            cb.clear()
            cb.blockSignals(False)
        self.refresh()

    def refresh(self):
        """重新读清单；没有清单就先给一份自动草稿。"""
        if not self.store:
            return
        self.items = R.load_plan(self.store.dir)
        if not self.items:
            self.items = R.suggest_plan(self.store)
            if self.items:
                R.save_plan(self.store.dir, self.items)
        self.results = R.compute_all(self.store, self.items)
        self._fill_file_boxes()
        self._fill_table()
        if self.items:
            self.table.selectRow(0)
        else:
            self.cur = -1
            self.preview.set_data(None, "清单是空的，点【添加测点】开始")
        self._update_hint()

    def _group_choices(self) -> list[tuple[str, str, str]]:
        """(显示文本, 1/3 文件名, 1/1 文件名)"""
        out = []
        if not self.store:
            return out
        gid_by_name = {}
        for name in self.store.records:
            gid_by_name[name] = self.store.group_of(name)
        for g in self.store.groups():
            gid = g["gid"]
            f13 = f"1_3_{gid}.AWA"
            f11 = f"OCT_{gid}.AWA"
            has13 = f13 in self.store.records
            has11 = f11 in self.store.records
            if not (has13 or has11):
                continue
            tail = g.get("point") or ""
            t = (g.get("time") or "")[:8]
            label = f"{gid}　{tail}　{t}".strip()
            out.append((label, f13 if has13 else "",
                        f11 if has11 else ""))
        return out

    def _fill_file_boxes(self):
        choices = self._group_choices()
        self._loading = True
        for cb, idx in ((self.cb_inner, 1), (self.cb_outer, 1)):
            cb.clear()
            cb.addItem("（未选）", "")
            for label, f13, f11 in choices:
                cb.addItem(label, (f13, f11))
        self._loading = False

    def _fill_table(self):
        self.table.setRowCount(len(self.items))
        for i, (it, r) in enumerate(zip(self.items, self.results)):
            cells = [
                str(i + 1),
                it.name,
                it.kind,
                it.file or it.inner or "—",
                it.outer or "—",
                r.value or ("—" if r.ok else "缺数据"),
                "—" if r.pass_ is None else ("满足" if r.pass_ else "不满足"),
            ]
            for j, v in enumerate(cells):
                cell = QTableWidgetItem(str(v))
                cell.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                if j in (0, 2, 5, 6):
                    cell.setTextAlignment(Qt.AlignCenter)
                if j == 6 and r.pass_ is False:
                    cell.setForeground(QBrush(QColor(BAD)))
                elif j == 6 and r.pass_ is True:
                    cell.setForeground(QBrush(QColor(GOOD)))
                if j == 5 and not r.ok:
                    cell.setForeground(QBrush(QColor(WARN)))
                self.table.setItem(i, j, cell)

        widths = (38, 190, 70, 150, 150, 84, 62)
        for j, w in enumerate(widths):
            self.table.setColumnWidth(j, w)

    def _update_hint(self):
        total = len(self.items)
        ins = [r for r in self.results if r.item.kind == R.KIND_INSUL and r.ok]
        bad = [r for r in self.results if r.pass_ is False]
        n_img = len(ins)
        txt = f"{total} 个测点"
        if n_img:
            txt += f"　{n_img} 张曲线"
        if bad:
            txt += f"　{len(bad)} 项不满足设计值"
        self.lb_hint.setText(txt)

    # ------------------------------------------------------------ 交互 ---
    def _mark(self):
        R.save_plan(self.store.dir, self.items)
        self.results = R.compute_all(self.store, self.items)
        self._fill_table()
        if 0 <= self.cur < len(self.items):
            self.table.selectRow(self.cur)
        self._update_hint()

    def _on_select(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        self.cur = rows[0].row()
        self._load_form(self.cur)

    def _load_form(self, i: int):
        if not (0 <= i < len(self.items)):
            return
        it = self.items[i]
        r = self.results[i]
        self._loading = True
        self.ed_name.setText(it.name)
        self.cb_kind.setCurrentText(it.kind)
        self.ed_table.setText(it.table)
        self.ed_design.setText(it.design)
        self._select_file(self.cb_inner, it.file if it.kind == R.KIND_NOISE
                          else it.inner, want_noise=False)
        self._select_file(self.cb_outer, it.outer, want_noise=False, outer=True)
        self._loading = False
        self._show_result(r)

    def _select_file(self, cb: QComboBox, target: str, want_noise: bool,
                     outer: bool = False):
        if not target:
            cb.setCurrentIndex(0)
            return
        for k in range(cb.count()):
            data = cb.itemData(k)
            if not data:
                continue
            f13, f11 = data
            if target in (f13, f11):
                cb.setCurrentIndex(k)
                return
        cb.setCurrentIndex(0)

    def _show_result(self, r: R.Result):
        if not r.ok:
            self.lb_result.setText("—")
            self.lb_result.setStyleSheet(f"color:{WARN};font-size:12px;"
                                         f"font-weight:700;")
            self.lb_note.setText(r.error)
            self.nr_table.setRowCount(0)
            self.preview.set_data(None, r.error or "没有可画的曲线")
            return

        label = r.value or "—"
        if r.pass_ is True:
            label += f"　满足 {r.item.design}"
            color = GOOD
        elif r.pass_ is False:
            label += f"　未满足 {r.item.design}"
            color = BAD
        else:
            color = BLUE_DEEP
        self.lb_result.setText(label)
        self.lb_result.setStyleSheet(f"color:{color};font-size:13px;"
                                     f"font-weight:700;")

        if r.item.kind == R.KIND_INSUL:
            bad = [RC._label(hz) for hz, d in zip(R.BANDS_THIRD, r.deficit) if d]
            note = f"内 {r.item.inner}　外 {r.item.outer}"
            if bad:
                note += f"　扣分频带：{'、'.join(bad)} Hz"
            self.lb_note.setText(note)
            self._fill_grid(R.BANDS_THIRD, r.bands, "NR")
            self.preview.set_data(RC.ChartData(
                R.BANDS_THIRD, r.bands, r.nic,
                title=f"{r.item.name}　声压级差 NR"), "")
        else:
            note = f"文件 {r.item.file}"
            if r.nc is not None:
                note += f"　NC 取自仪器"
            self.lb_note.setText(note)
            self._fill_grid(R.BANDS_OCT, r.bands, "声级")
            self.preview.set_data(None, "噪声级测点见「噪声级」工作表")

    def _fill_grid(self, bands, values, unit: str):
        """把逐个频带的数值摊成左右两栏（9+9 / 4+4），和报告表的版式一致。"""
        n = len(bands)
        half = (n + 1) // 2
        self.nr_table.clearContents()
        self.nr_table.setRowCount(half)
        self.nr_table.setHorizontalHeaderLabels(
            ["频带", f"{unit} (dB)", "频带", f"{unit} (dB)"])
        for i in range(half):
            for blk in (0, 1):
                j = i + blk * half
                if j >= n:
                    continue
                c0, c1 = blk * 2, blk * 2 + 1
                it_b = QTableWidgetItem(R.band_text(bands[j]))
                it_b.setTextAlignment(Qt.AlignCenter)
                it_b.setForeground(QBrush(QColor(TEXT2)))
                it_v = QTableWidgetItem(str(R.half_up(values[j])))
                it_v.setTextAlignment(Qt.AlignCenter)
                f = QFont("Consolas")
                f.setPointSizeF(9.5)
                it_v.setFont(f)
                self.nr_table.setItem(i, c0, it_b)
                self.nr_table.setItem(i, c1, it_v)

    def copy_values(self):
        """复制当前测点的频带表（Tab 分隔），直接粘到 Word 就是一张表。"""
        if not (0 <= self.cur < len(self.results)):
            return
        r = self.results[self.cur]
        if not r.ok:
            return
        bands = R.BANDS_THIRD if r.item.kind == R.KIND_INSUL else R.BANDS_OCT
        unit = "NR" if r.item.kind == R.KIND_INSUL else "声级"
        half = (len(bands) + 1) // 2
        lines = [f"频带\t{unit}(dB)\t频带\t{unit}(dB)"]
        for i in range(half):
            row = []
            for blk in (0, 1):
                j = i + blk * half
                if j >= len(bands):
                    row += ["", ""]
                    continue
                row += [R.band_text(bands[j]), str(R.half_up(r.bands[j]))]
            lines.append("\t".join(row))
        head = f"{r.item.name}\t{r.value or ''}"
        QApplication.clipboard().setText(head + "\n" + "\n".join(lines))
        self.lb_hint.setText(f"已复制 {r.item.name} 的 {len(bands)} 个频带值")

    def _apply_form(self):
        if self._loading or not (0 <= self.cur < len(self.items)):
            return
        it = self.items[self.cur]
        it.name = str(self.ed_name.text() or "").strip()
        it.kind = str(self.cb_kind.currentText() or R.KIND_INSUL)
        it.table = str(self.ed_table.text() or "").strip()
        it.design = str(self.ed_design.text() or "").strip()

        d_in = self.cb_inner.currentData() or ("", "")
        d_out = self.cb_outer.currentData() or ("", "")
        if it.kind == R.KIND_NOISE:
            it.file = d_in[1]
            it.inner = ""
            it.outer = ""
        else:
            it.inner = d_in[0]
            it.outer = d_out[0]
            it.file = ""
        self._mark()

    def add_item(self):
        n = len(self.items) + 1
        self.items.append(R.Item(name=f"测点{n}", kind=R.KIND_INSUL,
                                 order=n))
        self.cur = len(self.items) - 1
        self._mark()
        self.table.selectRow(self.cur)

    def remove_item(self):
        if not (0 <= self.cur < len(self.items)):
            return
        del self.items[self.cur]
        self.cur = min(self.cur, len(self.items) - 1)
        self._mark()
        if self.items:
            self.table.selectRow(self.cur)

    def auto_pair(self):
        """按测量时间把隔声测点两两配对，已有配对的跳过。"""
        if not self.store:
            return
        groups = self.store.groups()
        used = {it.inner for it in self.items if it.inner}
        used |= {it.outer for it in self.items if it.outer}

        free = [g for g in groups if f"1_3_{g['gid']}.AWA" not in used]
        free.sort(key=lambda g: (g.get("date") or "", g.get("time") or ""))
        made = 0
        i = 0
        while i + 1 < len(free):
            a, b = free[i], free[i + 1]
            self.items.append(R.Item(
                name=f"{a.get('point') or a['gid']} 隔声",
                kind=R.KIND_INSUL, order=len(self.items) + 1,
                inner=f"1_3_{a['gid']}.AWA",
                outer=f"1_3_{b['gid']}.AWA"))
            made += 1
            i += 2
        self.cur = len(self.items) - 1 if self.items else -1
        self._mark()
        QMessageBox.information(self, "按时间配对",
                                f"新配了 {made} 组。\n"
                                "配对是按测量时间相邻猜的，请逐组核对内/外，"
                                "配错的 NIC 会很小甚至为负。")

    # ------------------------------------------------------------ 生成 ---
    def generate(self):
        if not self.items:
            QMessageBox.warning(self, "还没测点", "先添加测点再生成。")
            return
        ok = [r for r in self.results if r.ok]
        if not ok:
            QMessageBox.warning(self, "没有可用数据",
                                "清单里没有算得出来的测点，检查文件选择。")
            return

        default = os.path.join(self.store.dir, "报告输出")
        out_dir = QFileDialog.getExistingDirectory(
            self, "选择输出文件夹", default)
        if not out_dir:
            return

        project = str(self.ed_project.text() or "").strip() or "报告数据"
        stamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")
        xlsx = os.path.join(out_dir, f"{project}_数据表.xlsx")
        try:
            R.write_xlsx(ok, xlsx, {
                "项目": project,
                "数据目录": self.store.dir,
                "生成时间": stamp,
            })
        except Exception as e:                       # noqa: BLE001
            QMessageBox.critical(self, "生成失败", f"写 xlsx 出错：\n{e}")
            return

        img_dir = os.path.join(out_dir, "曲线")
        os.makedirs(img_dir, exist_ok=True)
        made, failed = 0, []
        for r in ok:
            if r.item.kind != R.KIND_INSUL:
                continue
            safe = "".join(ch for ch in r.item.name
                           if ch not in '\\/:*?"<>|').strip() or "测点"
            try:
                RC.render_png(RC.ChartData(
                    R.BANDS_THIRD, r.bands, r.nic,
                    title=f"{r.item.name}　声压级差 NR"),
                    os.path.join(img_dir, f"{safe}.png"))
                made += 1
            except Exception as e:                   # noqa: BLE001
                failed.append(f"{r.item.name}: {e}")

        msg = [f"表格：{xlsx}", f"曲线：{made} 张（{img_dir}）"]
        if failed:
            msg.append("\n以下曲线没画出来：\n" + "\n".join(failed[:5]))
        QMessageBox.information(self, "生成完成", "\n".join(msg))
