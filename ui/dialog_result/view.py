"""
试验结果对话框 - 显示试验数据表格
"""
from __future__ import annotations
from PySide6.QtCore import QEvent, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class ResultTable(QTableWidget):
    """试验结果表格: 支持回车后按 TAB 次序轮换编辑焦点"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # TAB 值 -> 行号 映射, 由 ResultDialog 填充表格后建立
        self.tab_rows: dict[int, int] = {}

    def keyPressEvent(self, event) -> None:
        """回车: 按当前行 TAB 值找到下一个轮换行, 激活其测量值并进入编辑"""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current = self.currentRow()
            # 当前行 TAB 值; 不在轮换表中(或 TAB=-1)则从 0 开始
            cur_tab = next(
                (t for t, r in self.tab_rows.items() if r == current), -1
            )
            next_tab = cur_tab + 1
            if next_tab not in self.tab_rows:
                next_tab = 0  # 到达最大值后循环
            if next_tab in self.tab_rows:
                row = self.tab_rows[next_tab]
                self.setCurrentCell(row, self._dialog_col_std)
                self.edit(self.model().index(row, self._dialog_col_std))
                return
        super().keyPressEvent(event)


class Window(QDialog):
    """试验结果对话框 - 模态窗口"""

    def __init__(self, test_result: list, workflow: Workflow, parent=None) -> None:
        """
        初始化试验结果对话框

        Args:
            test_result: 试验结果数据列表，格式为 [ (数据项名, { "测量值": ..., "最小值": ..., "最大值": ..., "单位": ..., "结论": ... }), ... ]
            parent: 父窗口
        """
        super().__init__(parent)
        self.setWindowTitle("试验结果")
        self.setMinimumSize(800, 600)
        self._build_ui(test_result)
        self._workflow = workflow

    def _build_ui(self, test_result: list) -> None:
        """构建UI"""
        layout = QVBoxLayout(self)

        # 创建表格（6列：数据项、测量值、最小值、最大值、单位、结论）
        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(["数据项", "测量值", "最小值", "最大值", "单位", "结论"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)

        # 设置列宽自适应
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        for i in range(6):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        # 填充数据
        self._populate_table(test_result)

        layout.addWidget(self.table)

        # 按钮区域
        button_layout = QHBoxLayout()

        self.export_btn = QPushButton("导出报告", self)
        self.upload_btn = QPushButton("上传报告", self)
        self.close_btn = QPushButton("关闭", self)

        button_layout.addStretch()
        button_layout.addWidget(self.export_btn)
        button_layout.addWidget(self.upload_btn)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

        # 连接信号
        self.close_btn.clicked.connect(self.accept)
        self.export_btn.clicked.connect(self._on_export)
        self.upload_btn.clicked.connect(self._on_upload)

    def _populate_table(self, test_result: list) -> None:
        """填充表格数据"""
        for item_name, item_data in test_result:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # 数据项名称
            name_item = QTableWidgetItem(item_name)
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, name_item)

            # 测量值
            std_item = QTableWidgetItem(str(item_data.get("测量值", "")))
            std_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, std_item)

            # 最小值
            min_item = QTableWidgetItem(str(item_data.get("最小值", "")))
            min_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, min_item)

            # 最大值
            max_item = QTableWidgetItem(str(item_data.get("最大值", "")))
            max_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, max_item)

            # 单位
            unit_item = QTableWidgetItem(str(item_data.get("单位", "")))
            unit_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, unit_item)

            # 结论 - 根据结果设置颜色
            result_item = QTableWidgetItem(str(item_data.get("结论", "")))
            result_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._apply_result_color(result_item, item_data.get("结论", ""))
            self.table.setItem(row, 5, result_item)

    def _apply_result_color(self, item: QTableWidgetItem, result: str) -> None:
        """根据结果设置单元格颜色"""
        if result == "合格":
            item.setBackground(QBrush(QColor(200, 230, 200)))
        elif result == "不合格":
            item.setBackground(QBrush(QColor(255, 180, 180)))

    def _on_export(self) -> None:
        """导出报告按钮点击处理"""
        from PySide6.QtWidgets import QFileDialog
        import json

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出报告",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self._get_table_data(), f, ensure_ascii=False, indent=2)

    def _on_upload(self) -> None:
        """上传报告按钮点击处理"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择报告文件",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            QMessageBox.information(self, "提示", f"已选择文件: {file_path}\n上传功能待实现")

    def _get_table_data(self) -> dict:
        """获取表格数据为字典"""
        result = {}
        for row in range(self.table.rowCount()):
            item_name = self.table.item(row, 0).text()
            result[item_name] = {
                "测量值": self.table.item(row, 1).text(),
                "最小值": self.table.item(row, 2).text(),
                "最大值": self.table.item(row, 3).text(),
                "单位": self.table.item(row, 4).text(),
                "结论": self.table.item(row, 5).text(),
            }
        return result


class ResultDialog(QDialog):
    """
    试验结果对话框（可阻塞等待版本）
    用于在工作流中显示结果并等待用户确认

    使用方式:
        dialog = ResultDialog(test_result, parent)
        result = dialog.blocking_exec()

    表格列:
        0 - 数据项（只读）
        1 - 测量值（可编辑）
        2 - 最小值（可编辑）
        3 - 最大值（可编辑）
        4 - 单位（只读）
        5 - 结论（自动计算）
    """

    confirmed = Signal(bool)

    # 列索引常量
    COL_NAME = 0
    COL_STD = 1
    COL_MIN = 2
    COL_MAX = 3
    COL_UNIT = 4
    COL_RESULT = 5

    def __init__(
        self,
        test_result: list,
        parent=None,
        result_store: dict | None = None,
        checker: str | None = None,
    ) -> None:
        """
        初始化试验结果对话框

        Args:
            test_result: 试验结果数据列表，格式为 [ (数据项名, { "测量值": ..., "最小值": ..., "最大值": ..., "单位": ..., "结论": ... }), ... ]
            parent: 父窗口
            result_store: 结果数据仓库。传入后进入"补录模式": 确认时把编辑结果写回该字典,
                并且不再触碰 runtime 中的当前 workflow (用于历史记录补录); 为 None 时
                沿用原有行为, 写回 get_runtime()["wf"].data["结果数据"]
            checker: 补录模式下互检员的初始值; 为 None 时从 runtime 当前 workflow.meta 读取
        """
        super().__init__(parent)
        self.setWindowTitle("试验结果")
        self.setMinimumSize(900, 650)
        # 补录模式: 结果写回外部仓库而非运行中的 workflow
        self._result_store: dict | None = result_store
        self._checker_init: str | None = checker
        self.checker: str = checker or ""
        self._build_ui(test_result)

    def _build_ui(self, test_result: list) -> None:
        """构建UI"""
        layout = QVBoxLayout(self)

        # 互检员选择行: 只读下拉, 只能从用户库候选中选取(避免误删/误改文本)
        checker_row = QHBoxLayout()
        checker_row.addWidget(QLabel("互检员"))
        self.checker_combo = QComboBox(self)
        self.checker_combo.setEditable(False)
        self.checker_combo.setMinimumWidth(200)
        self._load_checker_candidates()
        checker_row.addWidget(self.checker_combo)
        checker_row.addStretch()
        layout.addLayout(checker_row)

        # 创建表格（6列）
        self.table = ResultTable(0, 6, self)
        self.table.setHorizontalHeaderLabels([
            "数据项", "测量值", "最小值", "最大值", "单位", "结论"
        ])
        # 告知表格"测量值"列索引, 供回车轮换定位
        self.table._dialog_col_std = self.COL_STD
        # 只允许编辑测量值、最小值、最大值列
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)

        # 设置列宽自适应
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        for i in range(6):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        # 连接单元格变化信号
        self.table.itemChanged.connect(self._on_item_changed)

        # 填充数据
        self._populate_table(test_result)

        layout.addWidget(self.table)

        # 按钮区域
        button_layout = QHBoxLayout()

        self.confirm_btn = QPushButton("确认", self)
        self.confirm_btn.setDefault(True)
        self.cancel_btn = QPushButton("取消", self)

        button_layout.addStretch()
        button_layout.addWidget(self.confirm_btn)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

        # 连接信号
        self.confirm_btn.clicked.connect(lambda: self._finish(True))
        self.cancel_btn.clicked.connect(lambda: self._finish(False))

    def _load_checker_candidates(self) -> None:
        """加载互检员候选: 用户数据库(TblUser)用户名, 首项为空.

        默认选中当前 workflow.meta 已有的互检员(若该名字仍在候选列表中), 否则留空;
        数据库读取失败时候选列表仅剩空项, 不阻断结果确认.
        """
        candidates: list[str] = []
        try:
            import sqlite3

            from _runtime import get_runtime

            db_path = get_runtime()["paths"]["db"]
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT UserName FROM TblUser
                    WHERE UserName IS NOT NULL AND TRIM(UserName) <> ''
                    ORDER BY LOWER(UserName)
                    """
                ).fetchall()
            candidates = [str(row[0]).strip() for row in rows]
        except Exception:  # noqa: BLE001
            # 数据库不可用时下拉只剩空项, 不阻断结果确认
            import logging

            logging.getLogger(__name__).exception("failed to load user candidates")

        # 补录模式: 互检员初始值由调用方指定(来自日志元信息), 不再依赖运行中的 workflow
        if self._checker_init is not None:
            current = self._checker_init
        else:
            try:
                from _runtime import get_runtime

                wf = get_runtime().get("wf")
                current = str((getattr(wf, "meta", {}) or {}).get("互检员") or "")
            except Exception:  # noqa: BLE001
                current = ""


        self.checker_combo.addItem("")
        self.checker_combo.addItems(candidates)
        # 只读下拉不能用 setCurrentText 兜底(找不到文本时会置为 -1), 显式按索引回退到空项
        index = self.checker_combo.findText(current)
        self.checker_combo.setCurrentIndex(index if index >= 0 else 0)

    def _populate_table(self, test_result: list) -> None:
        """填充表格数据"""
        self.table.blockSignals(True)
        try:
            for item_name, item_data in test_result:
                row = self.table.rowCount()
                self.table.insertRow(row)

                # 数据项名称（只读）
                name_item = QTableWidgetItem(item_name)
                name_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, self.COL_NAME, name_item)

                # 测量值（可编辑）: 数值按 2 位小数展示, 非数值(如 '-')原样展示
                rlt = item_data.get("测量值", -1)
                try:
                    rlt = round(float(rlt), 2)
                except (TypeError, ValueError):
                    pass
                std_item = QTableWidgetItem(str(rlt))
                std_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, self.COL_STD, std_item)

                # 最小值（可编辑）
                min_item = QTableWidgetItem(str(item_data.get("最小值", "")))
                min_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, self.COL_MIN, min_item)

                # 最大值（可编辑）
                max_item = QTableWidgetItem(str(item_data.get("最大值", "")))
                max_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, self.COL_MAX, max_item)

                # 单位（只读）
                unit_item = QTableWidgetItem(str(item_data.get("单位", "")))
                unit_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                unit_item.setFlags(unit_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, self.COL_UNIT, unit_item)

                # 结论（自动计算，只读）
                result_item = QTableWidgetItem(item_data.get("结论", "-"))
                result_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                result_item.setFlags(result_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._apply_result_color(result_item, item_data.get("结论", "-"))
                self.table.setItem(row, self.COL_RESULT, result_item)
        finally:
            self.table.blockSignals(False)

        # 建立 TAB 值 -> 行号 映射（TAB=-1 或缺失的项不参与轮换）
        self.table.tab_rows = {
            item_data["TAB"]: row
            for row, (_, item_data) in enumerate(test_result)
            if isinstance(item_data.get("TAB"), int) and item_data["TAB"] >= 0
        }

    @Slot(QTableWidgetItem)
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """当单元格内容变化时，重新计算该行的结论"""
        if item is None:
            return

        row = item.row()
        col = item.column()

        # 只在编辑测量值、最小值、最大值时重新计算结论
        if col in (self.COL_STD, self.COL_MIN, self.COL_MAX):
            calc_custom = [
                "1位-电机侧联轴节高度",
                "2位-电机侧联轴节高度",
                "1位-齿轮箱侧联轴节高度",
                "2位-齿轮箱侧联轴节高度"
            ]
            if self.table.item(row, self.COL_NAME).text() in calc_custom:
                # 联轴节计算: 高度差 = 电机侧高度 - 齿轮箱侧高度
                self._calc_coupling_height_diff()

            corner_names = [
                "1位轴箱与构架间距",
                "2位轴箱与构架间距",
                "3位轴箱与构架间距",
                "4位轴箱与构架间距",
            ]
            if self.table.item(row, self.COL_NAME).text() in corner_names:
                # 轴箱与构架间距计算: 高差值 = 1/2/3/4位轴箱与构架间距 的极差(最大值 - 最小值)
                self._calc_four_corner_height_diff()

            val_text = self.table.item(row, self.COL_STD).text() if self.table.item(row, self.COL_STD) else ""
            min_text = self.table.item(row, self.COL_MIN).text() if self.table.item(row, self.COL_MIN) else ""
            max_text = self.table.item(row, self.COL_MAX).text() if self.table.item(row, self.COL_MAX) else ""

            try:
                result = "合格" if float(min_text) <= float(val_text) <= float(max_text) else "不合格"
            except ValueError:
                # 测量值/上下限中存在非数值(如 '-'), 无法判定
                return
            result_item = self.table.item(row, self.COL_RESULT)
            if result_item:
                result_item.setText(result)
                self._apply_result_color(result_item, result)

    def _name_to_row(self) -> dict[str, int]:
        """按名称建立表格行号索引(数据项名 -> 行号), 供各计算项定位."""
        mapping: dict[str, int] = {}
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, self.COL_NAME)
            if name_item is not None:
                mapping[name_item.text()] = row
        return mapping

    def _measured_value(self, row: int) -> float | None:
        """读取某行当前(可能已被用户修改的)测量值; 空值或不可解析则返回 None."""
        std_item = self.table.item(row, self.COL_STD)
        if std_item is None or not std_item.text().strip():
            return None
        try:
            return float(std_item.text())
        except ValueError:
            return None

    def _result_data_store(self) -> dict:
        """返回结果数据的写入目标: 补录模式为外部仓库, 否则为运行中的 workflow."""
        if self._result_store is not None:
            return self._result_store
        from _runtime import get_runtime

        return get_runtime()["wf"].data["结果数据"]

    def _apply_calc_result(self, name_to_row: dict[str, int], target_name: str, value: float) -> None:
        """把计算出的测量值写回工作流结果数据与目标行表格, 并重算目标行结论."""
        result_data = self._result_data_store()
        if target_name in result_data:
            result_data[target_name]["测量值"] = value

        target_row = name_to_row.get(target_name)
        if target_row is None:
            return
        target_std = self.table.item(target_row, self.COL_STD)
        if target_std is None or target_std.text() == str(value):
            return
        # 屏蔽信号，避免触发 _on_item_changed 递归
        self.table.blockSignals(True)
        target_std.setText(str(value))
        self.table.blockSignals(False)
        # 差值行变化后需要重算其结论
        self._refresh_row_result(target_row)

    def _calc_coupling_height_diff(self) -> None:
        """联轴节计算: 高度差 = 电机侧联轴节高度 - 齿轮箱侧联轴节高度"""
        name_to_row = self._name_to_row()

        pairs = [
            ("联轴节高度差1", "1位-电机侧联轴节高度", "1位-齿轮箱侧联轴节高度"),
            ("联轴节高度差2", "2位-电机侧联轴节高度", "2位-齿轮箱侧联轴节高度"),
        ]
        for target_name, motor_name, gearbox_name in pairs:
            motor_row = name_to_row.get(motor_name)
            gearbox_row = name_to_row.get(gearbox_name)
            if motor_row is None or gearbox_row is None:
                continue
            motor_val = self._measured_value(motor_row)
            gearbox_val = self._measured_value(gearbox_row)
            if motor_val is None or gearbox_val is None:
                continue

            diff = round(motor_val - gearbox_val, 2)
            self._apply_calc_result(name_to_row, target_name, diff)

    def _calc_four_corner_height_diff(self) -> None:
        """轴箱与构架间距计算: 四角高差值 = 1/2/3/4位轴箱与构架间距 的极差(最大值 - 最小值).

        四个源值缺任一则不计算, 避免因部分未测(0 值)得出错误差值.
        """
        name_to_row = self._name_to_row()

        target_name = "四角高差值"
        source_names = ["1位轴箱与构架间距", "2位轴箱与构架间距", "3位轴箱与构架间距", "4位轴箱与构架间距"]

        values: list[float] = []
        for name in source_names:
            row = name_to_row.get(name)
            if row is None:
                return
            value = self._measured_value(row)
            if value is None:
                return
            values.append(value)

        diff = round(max(values) - min(values), 2)
        self._apply_calc_result(name_to_row, target_name, diff)

    def _refresh_row_result(self, row: int) -> None:
        """重新计算指定行的结论"""
        val_text = self.table.item(row, self.COL_STD).text() if self.table.item(row, self.COL_STD) else ""
        min_text = self.table.item(row, self.COL_MIN).text() if self.table.item(row, self.COL_MIN) else ""
        max_text = self.table.item(row, self.COL_MAX).text() if self.table.item(row, self.COL_MAX) else ""

        try:
            result = "合格" if float(min_text) <= float(val_text) <= float(max_text) else "不合格"
        except ValueError:
            return
        result_item = self.table.item(row, self.COL_RESULT)
        if result_item:
            result_item.setText(result)
            self._apply_result_color(result_item, result)

    def _apply_result_color(self, item: QTableWidgetItem, result: str) -> None:
        """根据结果设置单元格颜色"""
        if result == "合格":
            item.setBackground(QBrush(QColor(200, 230, 200)))
        elif result == "不合格":
            item.setBackground(QBrush(QColor(255, 180, 180)))
        else:
            item.setBackground(QBrush())

    def _finish(self, result: bool) -> None:
        """完成对话框"""
        if result:
            # 用户点击"确认"时, 反写表格编辑数据到 workflow.data["结果数据"]
            self._sync_table_to_workflow()
            # 互检员写入 workflow.meta, 并以独立事件落盘供导出PDF读取
            self._sync_checker_to_workflow()
        self.confirmed.emit(result)
        self.done(QDialog.Accepted if result else QDialog.Rejected)

    def _sync_checker_to_workflow(self) -> None:
        """将互检员写回 runtime workflow.meta, 并追加 meta_update 日志事件.

        日志首行元信息在工作流启动时已写死, 后续 meta 变更需靠该事件传递,
        view_history._extract_meta 会用其覆盖合并.

        补录模式下不触碰运行中的 workflow, 只把结果记录在 self.checker 供调用方落盘.
        """
        checker = self.checker_combo.currentText().strip()
        self.checker = checker
        if self._result_store is not None:
            return
        try:
            from _runtime import get_runtime

            wf = get_runtime().get("wf")
            if wf is None:
                return
            wf.meta["互检员"] = checker
            wf._append_workflow_log("meta_update", meta=dict(wf.meta))
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("failed to sync checker to workflow meta")

    def _sync_table_to_workflow(self) -> bool:
        """将表格中的编辑数据反写到结果数据

        直接执行反写, 不弹窗确认。
        覆盖字段: 测量值 / 最小值 / 最大值 / 结论
        (单位列为只读展示, "打印"等标记字段不受影响)

        补录模式下写入传入的 result_store, 否则写入 workflow.data["结果数据"]。

        Returns:
            True 表示已反写
        """
        result_data = self._result_data_store()

        def _to_number(text: str):
            """能转数字则转数字, 否则保留原字符串"""
            try:
                return float(text)
            except (TypeError, ValueError):
                return text

        for name, fields in self._get_table_data().items():
            if name not in result_data:
                continue
            result_data[name]["测量值"] = _to_number(fields["测量值"])
            result_data[name]["最小值"] = _to_number(fields["最小值"])
            result_data[name]["最大值"] = _to_number(fields["最大值"])
            result_data[name]["结论"] = fields["结论"]
        return True

    def _get_table_data(self) -> dict:
        """获取表格数据"""
        result = {}
        for row in range(self.table.rowCount()):
            item_name = self.table.item(row, self.COL_NAME).text()
            val_text = self.table.item(row, self.COL_STD).text()
            try:
                val = float(val_text)
            except ValueError:
                val = val_text
            result[item_name] = {
                "测量值": self.table.item(row, self.COL_STD).text(),
                "最小值": self.table.item(row, self.COL_MIN).text(),
                "最大值": self.table.item(row, self.COL_MAX).text(),
                "单位": self.table.item(row, self.COL_UNIT).text(),
                "结论": self.table.item(row, self.COL_RESULT).text(),
            }
        return result

    def blocking_exec(self) -> bool:
        """
        阻塞执行，等待用户点击确认或取消
        返回 True 表示确认，False 表示取消
        """
        self.setModal(True)
        self.show()
        self._result = False

        def on_confirmed(result: bool):
            self._result = result

        self.confirmed.connect(on_confirmed)
        self.exec()
        return self._result