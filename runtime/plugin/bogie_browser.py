"""车型参数浏览器 (插件).

左栏多选车型, 右表按 (车型, 位号) 展开 bogies.json 的叶子值; 列可通过
"设定数据列" 弹窗从第一个车型→位号对象的展平路径中挑选. 默认列写在本
文件 (改完重启即生效, 不用重新编译); 列选择不持久化, 每次打开恢复默认.

权限: 插件所有人可开 (ADMIN_ONLY=False); 只有管理员可编辑单元格并保存,
普通用户只浏览 (表格只读、保存按钮置灰), 但可以打开设定数据列弹窗.

保存铁律: 单元格写回时必须按原值类型回转, 绝不更换类型 (数字仍是数字、
布尔仍是布尔、文本仍是文本); 无法按原类型解析的输入会被拒绝并恢复原值.
某一位号没有该列路径时单元格显示为空且不可编辑, 保存时不补写.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from _runtime import get_runtime, is_admin_user

TITLE = "车型参数浏览器"
ADMIN_ONLY = False

#: 默认数据列 (点分路径). 改这里即可换默认列, 重启程序生效.
DEFAULT_COLUMNS: tuple[str, ...] = (
    "试验参数.空载@压力1",
    "试验参数.空载@压力2",
    "试验参数.压头间距",
    "试验参数.压头快进位置",
)

_MISSING = object()
_REJECT = object()

_TYPE_NAMES = {
    bool: "布尔 (true/false)",
    int: "整数",
    float: "数字",
    str: "文本",
    list: "列表 (JSON)",
    type(None): "空值",
}


def _flatten(obj: dict, prefix: str = "") -> dict[str, Any]:
    """展平嵌套 dict 为 {点分路径: 叶子值}; 列表视为叶子, 不展开."""
    out: dict[str, Any] = {}
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten(value, path))
        else:
            out[path] = value
    return out


def _resolve(container: dict, path: str) -> Any:
    """按点分路径取值, 缺失返回 _MISSING."""
    current: Any = container
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _assign(container: dict, path: str, value: Any) -> None:
    """按点分路径写值; 调用方须已确认路径存在."""
    parts = path.split(".")
    current = container
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = value


def _format_value(value: Any) -> str:
    """叶子值 -> 单元格显示文本; 与 _coerce 互逆, 保证往返不丢类型."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _coerce(text: str, original: Any) -> Any:
    """把单元格文本按原值类型回转; 无法回转返回 _REJECT (绝不换类型)."""
    if isinstance(original, bool):
        lowered = text.strip().lower()
        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0"):
            return False
        return _REJECT
    if isinstance(original, int):
        try:
            parsed = json.loads(text)
        except ValueError:
            return _REJECT
        if isinstance(parsed, bool) or not isinstance(parsed, int):
            return _REJECT
        return parsed
    if isinstance(original, float):
        try:
            parsed = json.loads(text)
        except ValueError:
            return _REJECT
        if isinstance(parsed, bool) or not isinstance(parsed, (int, float)):
            return _REJECT
        return float(parsed)
    if isinstance(original, str):
        return text
    if isinstance(original, list):
        try:
            parsed = json.loads(text)
        except ValueError:
            return _REJECT
        return parsed if isinstance(parsed, list) else _REJECT
    if original is None:
        try:
            return json.loads(text)
        except ValueError:
            return text
    return _REJECT


class _ColumnPickerDialog(QDialog):
    """设定数据列: 左为全部可选路径, 右为当前列, >>/<< 挑列, 重置回默认."""

    def __init__(self, all_paths: list[str], current: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设定数据列")
        self.resize(720, 480)

        layout = QHBoxLayout(self)

        self._left = QListWidget(self)
        self._left.setSelectionMode(QListWidget.ExtendedSelection)
        self._left.addItems(all_paths)
        layout.addWidget(self._left, 1)

        middle = QVBoxLayout()
        middle.addStretch(1)
        to_right = QPushButton(">>", self)
        to_right.clicked.connect(self._move_to_right)
        middle.addWidget(to_right)
        to_left = QPushButton("<<", self)
        to_left.clicked.connect(self._move_to_left)
        middle.addWidget(to_left)
        reset_btn = QPushButton("重置", self)
        reset_btn.clicked.connect(self._reset)
        middle.addWidget(reset_btn)
        middle.addStretch(1)
        layout.addLayout(middle)

        right_box = QVBoxLayout()
        self._right = QListWidget(self)
        self._right.setSelectionMode(QListWidget.ExtendedSelection)
        self._right.addItems(current)
        right_box.addWidget(self._right, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok_btn = QPushButton("确认", self)
        ok_btn.clicked.connect(self.accept)
        buttons.addWidget(ok_btn)
        cancel_btn = QPushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        right_box.addLayout(buttons)
        layout.addLayout(right_box, 1)

    def _right_texts(self) -> list[str]:
        return [self._right.item(i).text() for i in range(self._right.count())]

    def _move_to_right(self) -> None:
        existing = set(self._right_texts())
        for item in self._left.selectedItems():
            if item.text() not in existing:
                self._right.addItem(item.text())
                existing.add(item.text())

    def _move_to_left(self) -> None:
        for item in self._right.selectedItems():
            self._right.takeItem(self._right.row(item))

    def _reset(self) -> None:
        self._right.clear()
        self._right.addItems(list(DEFAULT_COLUMNS))

    def selected_columns(self) -> list[str]:
        return self._right_texts()


class Window(QDialog):
    """车型参数浏览器主弹窗."""

    def __init__(self) -> None:
        super().__init__()
        self._admin = is_admin_user()
        self._columns: list[str] = list(DEFAULT_COLUMNS)
        self._modified = False
        self._rebuilding = False
        self._data: dict = self._load_data()
        self._build_ui()
        self._fill_models()
        self._rebuild_table()

    # ---------- 数据 ----------

    def _bogie_path(self) -> Path:
        return Path(get_runtime()["paths"]["bogie_config"])

    def _load_data(self) -> dict:
        try:
            return json.loads(self._bogie_path().read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "加载失败", f"读取 bogies.json 失败: {exc}")
            return {}

    def _model_names(self) -> list[str]:
        # 与首页 _load_bogie_catalog 同规则: 值为 dict 的顶层键, 排除 "车型".
        return [k for k, v in self._data.items() if isinstance(v, dict) and k != "车型"]

    def _first_position_object(self) -> dict:
        for model in self._model_names():
            positions = self._data[model]
            for obj in positions.values():
                if isinstance(obj, dict):
                    return obj
        return {}

    # ---------- 界面 ----------

    def _build_ui(self) -> None:
        self.resize(1100, 700)
        self.setMinimumSize(800, 500)
        layout = QVBoxLayout(self)

        title = QLabel("车型参数浏览器", self)
        title.setObjectName("cardTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        body = QHBoxLayout()

        left_box = QWidget(self)
        left_box.setMaximumWidth(240)
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("支持车型列表", left_box))
        self._model_list = QListWidget(left_box)
        self._model_list.setSelectionMode(QListWidget.ExtendedSelection)
        self._model_list.itemSelectionChanged.connect(self._rebuild_table)
        left_layout.addWidget(self._model_list, 1)
        left_layout.addWidget(QLabel("Ctrl+A 选择所有车型", left_box))
        # QListWidget 默认没有全选快捷键, 这里接上 Ctrl+A.
        self._select_all_shortcut = QShortcut(QKeySequence.StandardKey.SelectAll, self._model_list)
        self._select_all_shortcut.activated.connect(self._model_list.selectAll)
        body.addWidget(left_box)

        right_box = QVBoxLayout()
        table_title = QLabel("车型参数表", self)
        table_title.setObjectName("cardTitle")
        table_title.setAlignment(Qt.AlignCenter)
        right_box.addWidget(table_title)
        self._table = QTableWidget(self)
        if self._admin:
            self._table.setEditTriggers(
                QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed
            )
        else:
            self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.itemChanged.connect(self._on_item_changed)
        right_box.addWidget(self._table, 1)
        body.addLayout(right_box, 1)

        layout.addLayout(body, 1)

        buttons = QHBoxLayout()
        columns_btn = QPushButton("设定数据列", self)
        columns_btn.clicked.connect(self._open_column_picker)
        buttons.addWidget(columns_btn)
        buttons.addStretch(1)
        self._save_btn = QPushButton("保存修改", self)
        self._save_btn.setEnabled(self._admin)
        self._save_btn.clicked.connect(self._save)
        buttons.addWidget(self._save_btn)
        layout.addLayout(buttons)

    def _fill_models(self) -> None:
        self._model_list.clear()
        self._model_list.addItems(self._model_names())
        if self._model_list.count() > 0:
            self._model_list.item(0).setSelected(True)

    # ---------- 表格 ----------

    def _set_cell(self, row: int, col: int, text: str, editable: bool) -> None:
        item = QTableWidgetItem(text)
        flags = item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if editable:
            flags |= Qt.ItemIsEditable
        else:
            flags &= ~Qt.ItemIsEditable
        item.setFlags(flags)
        self._table.setItem(row, col, item)

    def _rebuild_table(self) -> None:
        self._rebuilding = True
        try:
            headers = ["车型", "位号", *self._columns]
            self._table.setColumnCount(len(headers))
            self._table.setHorizontalHeaderLabels(headers)
            rows: list[tuple[str, str, dict]] = []
            for row_idx in range(self._model_list.count()):
                item = self._model_list.item(row_idx)
                if item is None or not item.isSelected():
                    continue
                model = item.text()
                positions = self._data.get(model)
                if not isinstance(positions, dict):
                    continue
                for pos, obj in positions.items():
                    if isinstance(obj, dict):
                        rows.append((model, str(pos), obj))
            self._table.setRowCount(len(rows))
            for r, (model, pos, obj) in enumerate(rows):
                self._set_cell(r, 0, model, editable=False)
                self._set_cell(r, 1, pos, editable=False)
                for c, path in enumerate(self._columns, start=2):
                    value = _resolve(obj, path)
                    if value is _MISSING:
                        self._set_cell(r, c, "", editable=False)
                    else:
                        self._set_cell(r, c, _format_value(value), editable=self._admin)
            self._table.resizeColumnsToContents()
        finally:
            self._rebuilding = False

    def _set_columns(self, columns: list[str]) -> None:
        self._columns = list(columns)
        self._rebuild_table()

    def _open_column_picker(self) -> None:
        all_paths = list(_flatten(self._first_position_object()).keys())
        dlg = _ColumnPickerDialog(all_paths, self._columns, self)
        if dlg.exec() == QDialog.Accepted:
            self._set_columns(dlg.selected_columns())

    # ---------- 编辑与保存 ----------

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._rebuilding or not self._admin:
            return
        row, col = item.row(), item.column()
        if col < 2:
            return
        model_item = self._table.item(row, 0)
        pos_item = self._table.item(row, 1)
        if model_item is None or pos_item is None:
            return
        positions = self._data.get(model_item.text())
        obj = positions.get(pos_item.text()) if isinstance(positions, dict) else None
        if not isinstance(obj, dict):
            return
        path = self._columns[col - 2]
        original = _resolve(obj, path)
        if original is _MISSING:
            self._rewrite_cell(item, "")
            return
        new_value = _coerce(item.text(), original)
        if new_value is _REJECT:
            self._rewrite_cell(item, _format_value(original))
            QMessageBox.warning(
                self,
                "类型不匹配",
                f"该项原类型为 {_TYPE_NAMES.get(type(original), type(original).__name__)}, "
                "输入无法按原类型解析, 已恢复原值。",
            )
            return
        _assign(obj, path, new_value)
        self._modified = True
        self._rewrite_cell(item, _format_value(new_value))

    def _rewrite_cell(self, item: QTableWidgetItem, text: str) -> None:
        """回写单元格显示 (规范格式 / 拒绝后恢复), 不触发二次处理."""
        self._rebuilding = True
        try:
            item.setText(text)
        finally:
            self._rebuilding = False

    def _save(self) -> None:
        if not self._admin:
            return
        path = self._bogie_path()
        try:
            path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", f"写入 {path} 失败: {exc}")
            return
        self._modified = False
        QMessageBox.information(self, "已保存", "车型参数已保存到 bogies.json, 新开工单即生效。")
