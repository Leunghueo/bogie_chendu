from __future__ import annotations

"""点位总表（原 dialog_plc 改名而来）：PLC / VSP / CAN 三张表。

轮询机制（任务第 3 点的结论，写在这里免得后人又加一个 timer）：
- 不用页面自己的 QTimer。plc/vsp/can 各自已经在自己的线程里轮询
  （plc 500ms、vsp 300ms、can 300ms），每轮结束都会经 broker 发
  plc_poll / vsp_poll / can_poll，页面只订阅这三个事件。
- 页面 timer 再轮询只会带来两害：要么只是刷新缓存里的值（多余的
  定时器，频率还跟源头对不上），要么直接调 poll/read 去碰硬件
  （多一份 Modbus/TCP/CAN 流量，还跟源头线程抢锁）。
- broker 回调跑在轮询线程上，所以先经 Qt Signal 转到主线程再刷表，
  这是原 dialog_plc 就用的做法，本页沿用。
- 哪个源头来了事件就只刷哪张表；打开页面时 showEvent 再全量刷一次。
"""

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QBrush
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from _runtime import get_runtime
from plc import BaseAct
from ui.dialog_fit.view import Window as FitWindow


def _segs_str(segs: Any) -> str:
    segments = getattr(segs, "segments", None)
    if not segments:
        return ""
    return ";".join(f"{seg.source}@{seg.target}" for seg in segments)


class Window(QWidget):
    _poll_signal = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = get_runtime()
        # 兼容旧名：self.table 仍指 plc 表；新增 vsp/can 各自的表引用。
        self.table = self.runtime.get("plc")
        self.plc_table = self.table
        self.vsp_table = self.runtime.get("vsp")
        self.can_table = self.runtime.get("can")

        self._poll_signal.connect(self._apply_poll_update)

        self.setObjectName("ptsDialog")
        size_policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setSizePolicy(size_policy)

        self._setup_ui()
        self._attach_tables()

        self._broker_subscriptions: list[object] = []
        self._subscribe()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._refresh_values()
        self._refresh_vsp_values()
        self._refresh_can_values()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        header_card = QFrame(self)
        header_card.setObjectName("homeStatusBar")
        status_row = QHBoxLayout(header_card)
        status_row.setContentsMargins(8, 6, 8, 6)
        status_row.setSpacing(6)

        self._plc_status_label = QLabel("PLC: 未启用", header_card)
        self._vsp_status_label = QLabel("VSP: 未启用", header_card)
        self._can_status_label = QLabel("CAN: 未启用", header_card)
        if self.plc_table is not None:
            self._plc_status_label.setText("PLC: 连接中")
        if self.vsp_table is not None:
            self._vsp_status_label.setText("VSP: 连接中")
        if self.can_table is not None:
            self._can_status_label.setText("CAN: 连接中")
        self._last_poll_label = QLabel("最后轮询: -", header_card)
        self._full_mode_checkbox = QCheckBox("完整模式", header_card)
        self._full_mode_checkbox.setToolTip("勾选后显示“分段系数”和“描述”列")
        self._full_mode_checkbox.setChecked(False)
        self._full_mode_checkbox.toggled.connect(self._on_full_mode_toggled)
        status_row.addWidget(self._plc_status_label)
        status_row.addWidget(self._vsp_status_label)
        status_row.addWidget(self._can_status_label)
        status_row.addStretch()
        status_row.addWidget(self._full_mode_checkbox)
        status_row.addWidget(self._last_poll_label)
        root.addWidget(header_card)

        self._tabs = QTabWidget(self)
        root.addWidget(self._tabs, 1)

        # ---- PLC 页签：沿用原 dialog_plc 的输入/输出分栏 ----
        plc_container = QWidget(self)
        plc_layout = QVBoxLayout(plc_container)
        plc_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal, plc_container)
        plc_layout.addWidget(splitter, 1)

        in_container = QWidget(plc_container)
        in_layout = QVBoxLayout(in_container)
        in_layout.setContentsMargins(0, 0, 0, 0)
        in_layout.addWidget(QLabel("读取 (Input)", in_container))
        self._pt_table_in = self._make_table(
            ["名称", "类型", "地址", "单位", "分段系数", "原始值", "计算值", "描述"]
        )
        self._pt_table_in.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._pt_table_in.customContextMenuRequested.connect(self._show_pt_context_menu)
        self._pt_table_in.doubleClicked.connect(self._on_point_table_dblclick)
        in_layout.addWidget(self._pt_table_in)
        splitter.addWidget(in_container)

        out_container = QWidget(plc_container)
        out_layout = QVBoxLayout(out_container)
        out_layout.setContentsMargins(0, 0, 0, 0)
        out_layout.addWidget(QLabel("写入 (Output)", out_container))
        self._pt_table_out = self._make_table(
            ["名称", "类型", "地址", "单位", "分段系数", "原始值", "计算值", "描述"]
        )
        self._pt_table_out.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._pt_table_out.customContextMenuRequested.connect(self._show_pt_context_menu_out)
        self._pt_table_out.doubleClicked.connect(self._on_point_table_dblclick_out)
        out_layout.addWidget(self._pt_table_out)
        splitter.addWidget(out_container)
        splitter.setSizes([400, 400])
        self._tabs.addTab(plc_container, "PLC")

        # ---- VSP 页签：只读采集表，双击只标定，不写数据 ----
        vsp_container = QWidget(self)
        vsp_layout = QVBoxLayout(vsp_container)
        vsp_layout.setContentsMargins(0, 0, 0, 0)
        vsp_layout.addWidget(QLabel("采集 (VSP)", vsp_container))
        self._vsp_table_widget = self._make_table(
            ["名称", "地址", "单位", "分段系数", "原始值", "计算值", "状态"]
        )
        self._vsp_table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._vsp_table_widget.customContextMenuRequested.connect(
            lambda pos: self._show_generic_context_menu(self._vsp_table_widget, pos)
        )
        self._vsp_table_widget.doubleClicked.connect(self._on_vsp_table_dblclick)
        vsp_layout.addWidget(self._vsp_table_widget)
        self._tabs.addTab(vsp_container, "VSP")

        # ---- CAN 页签：只读采集表，双击只标定，不写数据 ----
        can_container = QWidget(self)
        can_layout = QVBoxLayout(can_container)
        can_layout.setContentsMargins(0, 0, 0, 0)
        can_layout.addWidget(QLabel("采集 (CAN)", can_container))
        self._can_table_widget = self._make_table(
            ["名称", "总线/节点", "单位", "分段系数", "原始值", "计算值", "报警", "状态"]
        )
        self._can_table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._can_table_widget.customContextMenuRequested.connect(
            lambda pos: self._show_generic_context_menu(self._can_table_widget, pos)
        )
        self._can_table_widget.doubleClicked.connect(self._on_can_table_dblclick)
        can_layout.addWidget(self._can_table_widget)
        self._tabs.addTab(can_container, "CAN")

    def _make_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(self)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.setStyleSheet("QTableWidget { background-color: #ffffff; alternate-background-color: #f5f5f5; }")
        return table

    def _attach_tables(self) -> None:
        self._populate_pt_table()
        self._populate_vsp_table()
        self._populate_can_table()
        self._refresh_values()
        self._refresh_vsp_values()
        self._refresh_can_values()

    # 兼容旧名：原来 _attach_table(table) 只接 plc 表。
    def _attach_table(self, table: Any) -> None:
        self.table = table
        self.plc_table = table
        self._populate_pt_table()
        self._refresh_values()

    def _populate_pt_table(self) -> None:
        if self.plc_table is None:
            self._pt_table_in.setRowCount(0)
            self._pt_table_out.setRowCount(0)
            self._pt_row_map_in = {}
            self._pt_row_map_out = {}
            return
        pts_in = [(name, pt) for name, pt in self.plc_table.points.items() if pt.show and pt.io == "i"]
        pts_out = [(name, pt) for name, pt in self.plc_table.points.items() if pt.show and pt.io == "o"]

        self._pt_table_in.clearContents()
        self._pt_table_in.setRowCount(len(pts_in))
        self._pt_row_map_in: dict[str, int] = {}
        for row, (name, pt) in enumerate(pts_in):
            addr = f"{pt.address.word}.{pt.address.bit}" if pt.address.bit is not None else str(pt.address.word)
            texts = [name, pt.point_type, addr, pt.unit or "", _segs_str(pt.segs), "-", "-", getattr(pt, "desc", "") or ""]
            for col, text in enumerate(texts):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col in (0, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self._pt_table_in.setItem(row, col, item)
            self._pt_row_map_in[name] = row

        self._pt_table_out.clearContents()
        self._pt_table_out.setRowCount(len(pts_out))
        self._pt_row_map_out: dict[str, int] = {}
        for row, (name, pt) in enumerate(pts_out):
            addr = f"{pt.address.word}.{pt.address.bit}" if pt.address.bit is not None else str(pt.address.word)
            texts = [name, pt.point_type, addr, pt.unit or "", _segs_str(pt.segs), "-", "-", getattr(pt, "desc", "") or ""]
            for col, text in enumerate(texts):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col in (0, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self._pt_table_out.setItem(row, col, item)
            self._pt_row_map_out[name] = row

        self._apply_column_visibility()

    def _populate_vsp_table(self) -> None:
        if self.vsp_table is None:
            self._vsp_table_widget.setRowCount(0)
            self._vsp_row_map: dict[str, int] = {}
            return
        points = list(self.vsp_table.points.items())
        self._vsp_table_widget.clearContents()
        self._vsp_table_widget.setRowCount(len(points))
        self._vsp_row_map = {}
        for row, (name, pt) in enumerate(points):
            addr = f"{pt.endpoint.host}@{pt.endpoint.port}"
            texts = [name, addr, pt.unit or "", _segs_str(pt.config.segs), "-", "-", "断开"]
            for col, text in enumerate(texts):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self._vsp_table_widget.setItem(row, col, item)
            self._vsp_row_map[name] = row
        self._apply_column_visibility()

    def _populate_can_table(self) -> None:
        if self.can_table is None:
            self._can_table_widget.setRowCount(0)
            self._can_row_map: dict[str, int] = {}
            return
        points = list(self.can_table.points.items())
        self._can_table_widget.clearContents()
        self._can_table_widget.setRowCount(len(points))
        self._can_row_map = {}
        for row, (name, pt) in enumerate(points):
            addr = f"{pt.config.bus} / 节点{pt.config.node}"
            texts = [name, addr, pt.unit or "", _segs_str(pt.config.segs), "-", "-", "-", "断开"]
            for col, text in enumerate(texts):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self._can_table_widget.setItem(row, col, item)
            self._can_row_map[name] = row
        self._apply_column_visibility()

    def _apply_column_visibility(self) -> None:
        """简洁模式隐藏分段系数列；PLC 另外隐藏描述列（沿用原逻辑）。"""
        full_mode = self._full_mode_checkbox.isChecked()
        for table in (self._pt_table_in, self._pt_table_out):
            header = table.horizontalHeader()
            for col in self._HIDDEN_COLUMNS:
                header.setSectionHidden(col, not full_mode)
        self._vsp_table_widget.horizontalHeader().setSectionHidden(3, not full_mode)
        self._can_table_widget.horizontalHeader().setSectionHidden(3, not full_mode)

    def _on_full_mode_toggled(self, checked: bool) -> None:
        del checked
        self._apply_column_visibility()

    def _refresh_values(self) -> None:
        if self.plc_table is None:
            return
        self._pt_table_in.setUpdatesEnabled(False)
        self._pt_table_out.setUpdatesEnabled(False)
        try:
            for table_widget, row_map in (
                (self._pt_table_in, getattr(self, "_pt_row_map_in", {})),
                (self._pt_table_out, getattr(self, "_pt_row_map_out", {})),
            ):
                for name, row in list(row_map.items()):
                    raw_item = table_widget.item(row, 5)
                    calc_item = table_widget.item(row, 6)
                    if calc_item is None:
                        continue
                    pt = self.plc_table.points.get(name)
                    try:
                        val = self.plc_table.read(name)
                        if pt and pt.point_type == "BOOL":
                            calc_text = "开" if val else "关"
                        else:
                            calc_text = str(val)
                        if calc_item.text() != calc_text:
                            calc_item.setText(calc_text)
                        calc_item.setForeground(self.palette().text().color())
                        if pt is not None and raw_item is not None:
                            raw_text = str(pt.raw_value) if pt.raw_value is not None else "-"
                            if raw_item.text() != raw_text:
                                raw_item.setText(raw_text)
                        if pt and pt.point_type.upper() == "BOOL":
                            for col in range(table_widget.columnCount()):
                                cell = table_widget.item(row, col)
                                if cell:
                                    cell.setBackground(QColor("#FFA500") if val else QBrush())
                    except Exception:
                        if calc_item.text() != "ERR":
                            calc_item.setText("ERR")
                            calc_item.setForeground(QColor("#de4258"))
        finally:
            self._pt_table_in.setUpdatesEnabled(True)
            self._pt_table_out.setUpdatesEnabled(True)

    def _refresh_vsp_values(self) -> None:
        if self.vsp_table is None:
            return
        self._vsp_table_widget.setUpdatesEnabled(False)
        try:
            for name, row in list(getattr(self, "_vsp_row_map", {}).items()):
                raw_item = self._vsp_table_widget.item(row, 4)
                calc_item = self._vsp_table_widget.item(row, 5)
                status_item = self._vsp_table_widget.item(row, 6)
                if calc_item is None:
                    continue
                pt = self.vsp_table.points.get(name)
                if pt is None:
                    continue
                try:
                    val = self.vsp_table.read(name)
                    calc_text = str(val) if val is not None else "ERR"
                    if calc_item.text() != calc_text:
                        calc_item.setText(calc_text)
                    calc_item.setForeground(self.palette().text().color())
                    if raw_item is not None:
                        raw_text = str(pt.raw_value) if pt.raw_value is not None else "-"
                        if raw_item.text() != raw_text:
                            raw_item.setText(raw_text)
                except Exception:
                    if calc_item.text() != "ERR":
                        calc_item.setText("ERR")
                        calc_item.setForeground(QColor("#de4258"))
                if status_item is not None:
                    status_text = "在线" if pt.alive else "断开"
                    if status_item.text() != status_text:
                        status_item.setText(status_text)
                    status_item.setToolTip(pt.error or "")
        finally:
            self._vsp_table_widget.setUpdatesEnabled(True)

    def _refresh_can_values(self) -> None:
        if self.can_table is None:
            return
        self._can_table_widget.setUpdatesEnabled(False)
        try:
            for name, row in list(getattr(self, "_can_row_map", {}).items()):
                raw_item = self._can_table_widget.item(row, 4)
                calc_item = self._can_table_widget.item(row, 5)
                alarm_item = self._can_table_widget.item(row, 6)
                status_item = self._can_table_widget.item(row, 7)
                if calc_item is None:
                    continue
                pt = self.can_table.points.get(name)
                if pt is None:
                    continue
                try:
                    val = self.can_table.read(name)
                    calc_text = str(val) if val is not None else "ERR"
                    if calc_item.text() != calc_text:
                        calc_item.setText(calc_text)
                    calc_item.setForeground(self.palette().text().color())
                    if raw_item is not None:
                        raw_text = str(pt.raw_value) if pt.raw_value is not None else "-"
                        if raw_item.text() != raw_text:
                            raw_item.setText(raw_text)
                except Exception:
                    if calc_item.text() != "ERR":
                        calc_item.setText("ERR")
                        calc_item.setForeground(QColor("#de4258"))
                if alarm_item is not None:
                    alarm_text = f"0x{pt.alarm:X}" if pt.alarm is not None else "-"
                    if alarm_item.text() != alarm_text:
                        alarm_item.setText(alarm_text)
                if status_item is not None:
                    status_text = "在线" if pt.alive else "断开"
                    if status_item.text() != status_text:
                        status_item.setText(status_text)
                    status_item.setToolTip(pt.error or "")
        finally:
            self._can_table_widget.setUpdatesEnabled(True)

    # 简洁模式下隐藏的列: 分段系数(4) / 描述(7)（PLC 表沿用原逻辑）
    _HIDDEN_COLUMNS = (4, 7)

    def _show_pt_context_menu(self, pos) -> None:
        self._show_generic_context_menu(self._pt_table_in, pos)

    def _show_pt_context_menu_out(self, pos) -> None:
        self._show_generic_context_menu(self._pt_table_out, pos)

    def _show_generic_context_menu(self, table_widget: QTableWidget, pos) -> None:
        index = table_widget.indexAt(pos)
        if not index.isValid():
            return
        name_item = table_widget.item(index.row(), 0)
        if name_item is None:
            return
        pt_name = name_item.text()
        menu = QMenu(self)
        copy_action = QAction("复制点名", menu)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(pt_name))
        menu.addAction(copy_action)
        menu.exec(table_widget.viewport().mapToGlobal(pos))

    def _on_plc_poll(self, **payload) -> None:
        self._poll_signal.emit({"topic": "plc_poll", **payload})

    def _on_vsp_poll(self, **payload) -> None:
        self._poll_signal.emit({"topic": "vsp_poll", **payload})

    def _on_can_poll(self, **payload) -> None:
        self._poll_signal.emit({"topic": "can_poll", **payload})

    @Slot(dict)
    def _apply_poll_update(self, payload: dict) -> None:
        topic = payload.get("topic")
        connected = bool(payload.get("alive"))
        error = str(payload.get("error") or "")
        if topic == "plc_poll":
            self._plc_status_label.setText("PLC: 在线" if connected else "PLC: 断开")
            self._plc_status_label.setToolTip(error)
            self._refresh_values()
        elif topic == "vsp_poll":
            self._vsp_status_label.setText("VSP: 在线" if connected else "VSP: 断开")
            self._vsp_status_label.setToolTip(error)
            self._refresh_vsp_values()
        elif topic == "can_poll":
            self._can_status_label.setText("CAN: 在线" if connected else "CAN: 断开")
            self._can_status_label.setToolTip(error)
            self._refresh_can_values()
        else:
            return
        ts = payload.get("last_poll_at")
        self._last_poll_label.setText(
            "最后轮询: " + datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "最后轮询: -"
        )

    # 兼容旧名：原来只有一个 _on_poll（plc 用）。
    @Slot(object)
    def _on_poll(self, **payload) -> None:
        self._on_plc_poll(**payload)

    def _on_point_table_dblclick(self, index) -> None:
        row = index.row()
        name_item = self._pt_table_in.item(row, 0)
        type_item = self._pt_table_in.item(row, 1)
        if name_item is None or type_item is None:
            return
        pt_name = name_item.text()
        pt = self.plc_table.points.get(pt_name) if self.plc_table is not None else None
        if pt is None:
            return
        modifiers = QApplication.keyboardModifiers()
        if modifiers == Qt.KeyboardModifier.ControlModifier:
            if pt.point_type == "BOOL":
                self._toggle_bool_point(pt_name, skip_act=True)
            else:
                self._prompt_and_write_point(pt_name, pt.point_type, skip_act=True)
        else:
            self._open_fit_dialog("plc", pt_name)

    def _on_point_table_dblclick_out(self, index) -> None:
        row = index.row()
        name_item = self._pt_table_out.item(row, 0)
        if name_item is None:
            return
        pt_name = name_item.text()
        pt = self.plc_table.points.get(pt_name) if self.plc_table is not None else None
        if pt is None:
            return
        if pt.point_type == "BOOL":
            self._toggle_bool_point(pt_name)
        else:
            self._prompt_and_write_point(pt_name, pt.point_type)

    def _on_vsp_table_dblclick(self, index) -> None:
        row = index.row()
        name_item = self._vsp_table_widget.item(row, 0)
        if name_item is None:
            return
        pt_name = name_item.text()
        if self.vsp_table is None or pt_name not in self.vsp_table.points:
            return
        # VSP 是只读采集：双击只开标定，不提供 ctrl+双击写数据。
        self._open_fit_dialog("vsp", pt_name)

    def _on_can_table_dblclick(self, index) -> None:
        row = index.row()
        name_item = self._can_table_widget.item(row, 0)
        if name_item is None:
            return
        pt_name = name_item.text()
        if self.can_table is None or pt_name not in self.can_table.points:
            return
        # CAN 是只读采集：双击只开标定，不提供 ctrl+双击写数据。
        self._open_fit_dialog("can", pt_name)

    def _open_fit_dialog(self, pt_type: str, pt_name: str) -> None:
        try:
            dialog = FitWindow(pt_type, pt_name, self)
        except Exception:
            QMessageBox.warning(self, "无法标定", "当前点位不支持标定!")
            return
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 标定保存会替换点表中的点对象，重新填充该源头的表并刷新。
            if pt_type == "plc":
                self._populate_pt_table()
                self._refresh_values()
            elif pt_type == "vsp":
                self._populate_vsp_table()
                self._refresh_vsp_values()
            elif pt_type == "can":
                self._populate_can_table()
                self._refresh_can_values()

    def _toggle_bool_point(self, pt_name: str, skip_act: bool = False) -> None:
        if self.plc_table is None:
            return
        try:
            current_value = self.plc_table.read(pt_name)
            new_value = not bool(current_value)
            if skip_act:
                self.plc_table.write(pt_name, new_value)
            else:
                act = BaseAct(pt_name=pt_name, value=new_value, reset=False)
                self.plc_table.act([act])
            self._refresh_values()
        except Exception as exc:
            QMessageBox.warning(self, "写入失败", f"点位 {pt_name} 写入失败: {exc}")

    def _prompt_and_write_point(self, pt_name: str, point_type: str, skip_act: bool = False) -> None:
        if self.plc_table is None:
            return
        try:
            current_value = self.plc_table.read(pt_name)
        except Exception:
            if point_type in {"WORD", "INT"}:
                current_value = 0
            else:
                current_value = 0.0
        if point_type in {"WORD", "INT"}:
            value, ok = QInputDialog.getInt(self, "输入值", f"请输入 {pt_name} 的新值:", value=int(current_value))
        else:
            value, ok = QInputDialog.getDouble(self, "输入值", f"请输入 {pt_name} 的新值:", value=float(current_value))
        if not ok:
            return
        try:
            if skip_act:
                self.plc_table.write(pt_name, value)
            else:
                act = BaseAct(pt_name=pt_name, value=value, reset=False)
                self.plc_table.act([act])
            self._refresh_values()
        except Exception as exc:
            QMessageBox.warning(self, "写入失败", f"点位 {pt_name} 写入失败: {exc}")

    def _reload(self) -> None:
        if self.plc_table is not None:
            self.plc_table.reload()
        if self.vsp_table is not None:
            self.vsp_table.reload()
        if self.can_table is not None:
            self.can_table.reload()
        self._populate_pt_table()
        self._populate_vsp_table()
        self._populate_can_table()
        self._refresh_values()
        self._refresh_vsp_values()
        self._refresh_can_values()

    def _subscribe(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            return
        self._broker_subscriptions = [
            broker.subscribe("plc_poll", self._on_plc_poll),
            broker.subscribe("vsp_poll", self._on_vsp_poll),
            broker.subscribe("can_poll", self._on_can_poll),
        ]

    def _unsubscribe(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            self._broker_subscriptions.clear()
            return
        for subscription in self._broker_subscriptions:
            broker.unsubscribe(subscription)
        self._broker_subscriptions.clear()

    def closeEvent(self, event) -> None:
        self._unsubscribe()
        super().closeEvent(event)
