from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QBrush
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from _runtime import get_runtime
from plc import BaseAct
from ui.dialog_fit.view import Window as FitWindow


class Window(QWidget):
    _poll_signal = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = get_runtime()
        self.table = None

        self._poll_signal.connect(self._apply_poll_update)

        self.setObjectName("plcDialog")
        # 设置 size policy 为 Expander，允许自适应缩放
        size_policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setSizePolicy(size_policy)

        self._setup_ui()
        self._attach_table(self.runtime["plc"])

        self._broker_subscriptions: list[object] = []
        self._subscribe()


    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._refresh_values()

    # def hideEvent(self, event) -> None:  # type: ignore[override]
    #     self._refresh_timer.stop()
    #     super().hideEvent(event)

    # def closeEvent(self, event) -> None:  # type: ignore[override]
    #     self.hide()
    #     event.ignore()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        header_card = QFrame(self)
        header_card.setObjectName("homeStatusBar")
        status_row = QHBoxLayout(header_card)
        status_row.setContentsMargins(8, 6, 8, 6)
        status_row.setSpacing(6)

        self._status_label = QLabel("状态: 连接中", header_card)
        self._last_poll_label = QLabel("最后轮询: -", header_card)
        self._full_mode_checkbox = QCheckBox("完整模式", header_card)
        self._full_mode_checkbox.setToolTip("勾选后显示“分段系数”和“描述”列")
        self._full_mode_checkbox.setChecked(False)
        self._full_mode_checkbox.toggled.connect(self._on_full_mode_toggled)
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        status_row.addWidget(self._full_mode_checkbox)
        status_row.addWidget(self._last_poll_label)
        root.addWidget(header_card)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(splitter, 1)

        in_container = QWidget(self)
        in_layout = QVBoxLayout(in_container)
        in_layout.setContentsMargins(0, 0, 0, 0)
        in_layout.addWidget(QLabel("读取 (Input)", in_container))
        self._pt_table_in = QTableWidget(self)
        self._pt_table_in.setColumnCount(8)
        self._pt_table_in.setHorizontalHeaderLabels(["名称", "类型", "地址", "单位", "分段系数", "原始值", "计算值", "描述"])
        self._pt_table_in.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._pt_table_in.horizontalHeader().setStretchLastSection(True)
        self._pt_table_in.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pt_table_in.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pt_table_in.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._pt_table_in.customContextMenuRequested.connect(self._show_pt_context_menu)
        self._pt_table_in.doubleClicked.connect(self._on_point_table_dblclick)
        self._pt_table_in.setAlternatingRowColors(True)
        self._pt_table_in.setStyleSheet("QTableWidget { background-color: #ffffff; alternate-background-color: #f5f5f5; }")
        in_layout.addWidget(self._pt_table_in)
        splitter.addWidget(in_container)

        out_container = QWidget(self)
        out_layout = QVBoxLayout(out_container)
        out_layout.setContentsMargins(0, 0, 0, 0)
        out_layout.addWidget(QLabel("写入 (Output)", out_container))
        self._pt_table_out = QTableWidget(self)
        self._pt_table_out.setColumnCount(8)
        self._pt_table_out.setHorizontalHeaderLabels(["名称", "类型", "地址", "单位", "分段系数", "原始值", "计算值", "描述"])
        self._pt_table_out.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._pt_table_out.horizontalHeader().setStretchLastSection(True)
        self._pt_table_out.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pt_table_out.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pt_table_out.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._pt_table_out.customContextMenuRequested.connect(self._show_pt_context_menu_out)
        self._pt_table_out.doubleClicked.connect(self._on_point_table_dblclick_out)
        self._pt_table_out.setAlternatingRowColors(True)
        self._pt_table_out.setStyleSheet("QTableWidget { background-color: #ffffff; alternate-background-color: #f5f5f5; }")
        out_layout.addWidget(self._pt_table_out)
        splitter.addWidget(out_container)

        splitter.setSizes([400, 400])
        root.addWidget(splitter, 1)

    def _attach_table(self, table: Any) -> None:
        self.table = table
        self._populate_pt_table()
        self._refresh_values()

    def _populate_pt_table(self) -> None:
        pts_in = [(name, pt) for name, pt in self.table.points.items() if pt.show and pt.io == "i"]
        pts_out = [(name, pt) for name, pt in self.table.points.items() if pt.show and pt.io == "o"]

        self._pt_table_in.clearContents()
        self._pt_table_in.setRowCount(len(pts_in))
        self._pt_row_map_in: dict[str, int] = {}
        for row, (name, pt) in enumerate(pts_in):
            addr = f"{pt.address.word}.{pt.address.bit}" if pt.address.bit is not None else str(pt.address.word)
            segs_obj = getattr(pt, 'segs', None)
            segs_str = ";".join(f"{seg.source}@{seg.target}" for seg in segs_obj.segments) if segs_obj and segs_obj.segments else ""
            texts = [name, pt.point_type, addr, pt.unit or "", segs_str, "-", "-", getattr(pt, 'desc', '') or ""]
            for col, text in enumerate(texts):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                if col == 7:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self._pt_table_in.setItem(row, col, item)
            self._pt_row_map_in[name] = row

        self._pt_table_out.clearContents()
        self._pt_table_out.setRowCount(len(pts_out))
        self._pt_row_map_out: dict[str, int] = {}
        for row, (name, pt) in enumerate(pts_out):
            addr = f"{pt.address.word}.{pt.address.bit}" if pt.address.bit is not None else str(pt.address.word)
            segs_obj = getattr(pt, 'segs', None)
            segs_str = ";".join(f"{seg.source}@{seg.target}" for seg in segs_obj.segments) if segs_obj and segs_obj.segments else ""
            texts = [name, pt.point_type, addr, pt.unit or "", segs_str, "-", "-", getattr(pt, 'desc', '') or ""]
            for col, text in enumerate(texts):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                if col == 7:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self._pt_table_out.setItem(row, col, item)
            self._pt_row_map_out[name] = row

        self._apply_column_visibility()

    def _apply_column_visibility(self) -> None:
        """按当前模式设置两个表格的列可见性(简洁模式隐藏 分段系数/描述 列)。"""
        full_mode = self._full_mode_checkbox.isChecked()
        for table in (self._pt_table_in, self._pt_table_out):
            header = table.horizontalHeader()
            for col in self._HIDDEN_COLUMNS:
                header.setSectionHidden(col, not full_mode)

    def _on_full_mode_toggled(self, checked: bool) -> None:
        del checked
        self._apply_column_visibility()

    def _refresh_values(self) -> None:
        if self.table is None:
            return
        self._pt_table_in.setUpdatesEnabled(False)
        self._pt_table_out.setUpdatesEnabled(False)
        try:
            row_map_in = self._pt_row_map_in
            for name, row in list(row_map_in.items()):
                type_item = self._pt_table_in.item(row, 1)
                raw_item = self._pt_table_in.item(row, 5)
                calc_item = self._pt_table_in.item(row, 6)
                if calc_item is None:
                    continue
                pt = self.table.points.get(name)
                try:
                    val = self.table.read(name)
                    if pt and pt.point_type == "BOOL":
                        calc_text = "开" if val else "关"
                    else:
                        calc_text = str(val)
                    if calc_item.text() != calc_text:
                        calc_item.setText(calc_text)
                    calc_item.setForeground(self.palette().text().color())
                    if pt is not None and raw_item is not None:
                        raw_val = pt.raw_value
                        raw_text = str(raw_val) if raw_val is not None else "-"
                        if raw_item.text() != raw_text:
                            raw_item.setText(raw_text)
                    if pt and pt.point_type.upper() == "BOOL":
                        for col in range(self._pt_table_in.columnCount()):
                            cell = self._pt_table_in.item(row, col)
                            if cell:
                                cell.setBackground(QColor("#FFA500") if val else QBrush())
                except Exception:
                    if calc_item.text() != "ERR":
                        calc_item.setText("ERR")
                        calc_item.setForeground(QColor("#de4258"))

            row_map_out = self._pt_row_map_out
            for name, row in list(row_map_out.items()):
                type_item = self._pt_table_out.item(row, 1)
                raw_item = self._pt_table_out.item(row, 5)
                calc_item = self._pt_table_out.item(row, 6)
                if calc_item is None:
                    continue
                pt = self.table.points.get(name)
                try:
                    val = self.table.read(name)
                    if pt and pt.point_type == "BOOL":
                        calc_text = "开" if val else "关"
                    else:
                        calc_text = str(val)
                    if calc_item.text() != calc_text:
                        calc_item.setText(calc_text)
                    calc_item.setForeground(self.palette().text().color())
                    if pt is not None and raw_item is not None:
                        raw_val = pt.raw_value
                        raw_text = str(raw_val) if raw_val is not None else "-"
                        if raw_item.text() != raw_text:
                            raw_item.setText(raw_text)
                    if pt and pt.point_type.upper() == "BOOL":
                        for col in range(self._pt_table_out.columnCount()):
                            cell = self._pt_table_out.item(row, col)
                            if cell:
                                cell.setBackground(QColor("#FFA500") if val else QBrush())
                except Exception:
                    if calc_item.text() != "ERR":
                        calc_item.setText("ERR")
                        calc_item.setForeground(QColor("#de4258"))
        finally:
            self._pt_table_in.setUpdatesEnabled(True)
            self._pt_table_out.setUpdatesEnabled(True)

    # 简洁模式下隐藏的列: 分段系数(4) / 描述(7)
    _HIDDEN_COLUMNS = (4, 7)

    def _show_pt_context_menu(self, pos) -> None:
        index = self._pt_table_in.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        name_item = self._pt_table_in.item(row, 0)
        if name_item is None:
            return
        pt_name = name_item.text()
        menu = QMenu(self)
        copy_action = QAction("复制点名", menu)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(pt_name))
        menu.addAction(copy_action)
        menu.exec(self._pt_table_in.viewport().mapToGlobal(pos))

    def _show_pt_context_menu_out(self, pos) -> None:
        index = self._pt_table_out.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        name_item = self._pt_table_out.item(row, 0)
        if name_item is None:
            return
        pt_name = name_item.text()
        menu = QMenu(self)
        copy_action = QAction("复制点名", menu)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(pt_name))
        menu.addAction(copy_action)
        menu.exec(self._pt_table_out.viewport().mapToGlobal(pos))

    @Slot(object)
    def _on_poll(self, **payload) -> None:
        # broker 在轮询线程上同步调用，emit Signal 让 Qt auto-queue 到主线程
        self._poll_signal.emit(dict(payload))

    @Slot(dict)
    def _apply_poll_update(self, payload: dict) -> None:
        connected = bool(payload.get("alive"))
        self._status_label.setText("状态: 在线" if connected else f'状态: 断开  {payload.get("error", "")}')
        ts = payload.get("last_poll_at")
        self._last_poll_label.setText(
            "最后轮询: " + datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "最后轮询: -"
        )
        self._refresh_values()


    def _on_point_table_dblclick(self, index) -> None:
        row = index.row()
        name_item = self._pt_table_in.item(row, 0)
        type_item = self._pt_table_in.item(row, 1)
        if name_item is None or type_item is None:
            return
        pt_name = name_item.text()
        pt = self.table.points.get(pt_name)
        if pt is None:
            return

        modifiers = QApplication.keyboardModifiers()
        if modifiers == Qt.KeyboardModifier.ControlModifier:
            if pt.point_type == "BOOL":
                self._toggle_bool_point(pt_name, skip_act=True)
            else:
                self._prompt_and_write_point(pt_name, pt.point_type, skip_act=True)
        else:
            self._open_fit_dialog(pt_name)

    def _on_point_table_dblclick_out(self, index) -> None:
        row = index.row()
        name_item = self._pt_table_out.item(row, 0)
        if name_item is None:
            return
        pt_name = name_item.text()
        pt = self.table.points.get(pt_name)
        if pt is None:
            return
        if pt.point_type == "BOOL":
            self._toggle_bool_point(pt_name)
        else:
            self._prompt_and_write_point(pt_name, pt.point_type)

    def _open_fit_dialog(self, pt_name: str) -> None:
        try:
            dialog = FitWindow("plc", pt_name, self)
        except Exception:
            QMessageBox.warning(self, "无法标定", f"当前点位不支持标定!")
            return
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 标定保存会替换 table.points 中的点对象, 重新加载全部点位数据更新显示
            self._populate_pt_table()
            self._refresh_values()

    def _toggle_bool_point(self, pt_name: str, skip_act: bool = False) -> None:
        try:
            current_value = self.table.read(pt_name)
            new_value = not bool(current_value)
            if skip_act:
                self.table.write(pt_name, new_value)
            else:
                act = BaseAct(pt_name=pt_name, value=new_value, reset=False)
                self.table.act([act])
            self._refresh_values()
        except Exception as exc:
            QMessageBox.warning(self, "写入失败", f"点位 {pt_name} 写入失败: {exc}")

    def _prompt_and_write_point(self, pt_name: str, point_type: str, skip_act: bool = False) -> None:
        try:
            current_value = self.table.read(pt_name)
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
                self.table.write(pt_name, value)
            else:
                act = BaseAct(pt_name=pt_name, value=value, reset=False)
                self.table.act([act])
            self._refresh_values()
        except Exception as exc:
            QMessageBox.warning(self, "写入失败", f"点位 {pt_name} 写入失败: {exc}")

    def _reload(self) -> None:
        self.table.reload()
        self._populate_pt_table()
        self._refresh_values()

    def _subscribe(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            return
        self._broker_subscriptions = [
            broker.subscribe("plc_poll", self._on_poll),
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
