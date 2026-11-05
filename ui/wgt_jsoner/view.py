from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)
from _runtime import get_runtime, reload_bed_data, update_runtime


ITEM_KIND_ROLE = Qt.UserRole
FORCE_STRING_KEYS = {"addr-2byte"}

class JsonTreeWidget(QTreeWidget):
    request_add_child = Signal()
    request_add_sibling = Signal()
    request_delete = Signal()

    def contextMenuEvent(self, event) -> None:  # type: ignore[override]
        menu = QMenu(self)
        add_sibling_action = menu.addAction("克隆该条目")
        add_child_action = menu.addAction("新增子条目")
        delete_action = menu.addAction("删除当前条目")

        selected_action = menu.exec(event.globalPos())
        if selected_action == add_child_action:
            self.request_add_child.emit()
        elif selected_action == add_sibling_action:
            self.request_add_sibling.emit()
        elif selected_action == delete_action:
            self.request_delete.emit()


class JsonEditorWidget(QWidget):
    data_changed = Signal(object)
    saved = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, source: dict | list | str | Path | None = None) -> None:
        super().__init__(parent)
        self._source_path: Path | None = None
        self._data: dict | list | None = None
        self._modified = False
        self._rebuilding = False
        #: 当前展开层级：深度 < 该值的容器节点展开，其余收起。
        #: 1 = 只展开根（默认收到第一层，第一层键可见但不展开）
        self._expand_level = 1
        self._build_ui()
        if source is None:
            source = {}
        self.set_source(source)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)

        self.title_label = QLabel("JSON 对象", self)
        self.title_label.setObjectName("cardTitle")
        header.addWidget(self.title_label, 1)

        self.expand_button = QPushButton("展开一层", self)
        self.expand_button.clicked.connect(lambda: self._set_expand_level(self._expand_level + 1))
        header.addWidget(self.expand_button)

        self.collapse_button = QPushButton("收起一层", self)
        self.collapse_button.clicked.connect(lambda: self._set_expand_level(self._expand_level - 1))
        header.addWidget(self.collapse_button)

        self.reload_button = QPushButton("重载", self)
        self.reload_button.clicked.connect(self.reload_source)
        header.addWidget(self.reload_button)

        self.save_button = QPushButton("保存", self)
        self.save_button.clicked.connect(lambda: self.save())
        header.addWidget(self.save_button)

        layout.addLayout(header)

        self.tree = JsonTreeWidget(self)
        self.tree.setObjectName("jsonEditorTree")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Key", "Value", "Type"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.SelectedClicked
        )
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.request_add_child.connect(self.add_child_item)
        self.tree.request_add_sibling.connect(self.add_sibling_item)
        self.tree.request_delete.connect(self.delete_current_item)
        # 列宽自适应：展开/收起后内容变化，合并高频信号后统一重算列宽
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(50)
        self._fit_timer.timeout.connect(self._fit_columns)
        self.tree.itemExpanded.connect(lambda *_: self._fit_timer.start())
        self.tree.itemCollapsed.connect(lambda *_: self._fit_timer.start())
        layout.addWidget(self.tree, 1)

    @property
    def source_path(self) -> Path | None:
        return self._source_path

    def set_source(self, source: dict | list | str | Path) -> None:
        if isinstance(source, (str, Path)):
            path = Path(source).resolve()
            self._source_path = path
            self._data = json.loads(path.read_text(encoding="utf-8"))
        elif isinstance(source, (dict, list)):
            self._source_path = None
            self._data = copy.deepcopy(source)
        else:
            raise TypeError("source must be a dict, list, str path, or Path")

        self._modified = False
        self._refresh_title()
        self._rebuild_tree()

        

    def reload_source(self) -> None:
        if self._source_path is None:
            return
        self.set_source(self._source_path)
        # 如果重载的是 PLC/VSP 配置文件，强制更新对应配置（即时生效）
        try:
            runtime = get_runtime()
            plc_config_path: Path | None = runtime["paths"].get("plc_config")
            vsp_config_path: Path | None = runtime["paths"].get("vsp_config")
            if plc_config_path is not None and self._source_path == plc_config_path.resolve():
                plc = runtime.get("plc")
                if plc is not None and hasattr(plc, "reload"):
                    plc.reload()
            elif vsp_config_path is not None and self._source_path == vsp_config_path.resolve():
                vsp = runtime.get("vsp")
                if vsp is not None and hasattr(vsp, "reload"):
                    vsp.reload()
        except Exception:
            pass

    def data(self) -> dict | list:
        if self._data is None:
            return {}
        return copy.deepcopy(self._data)

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path).resolve() if path is not None else self._source_path
        if target is None:
            raise ValueError("save path is required when source is not a file")

        self._sync_data_from_tree()
        payload = self._data if self._data is not None else {}
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        # 保存的是 bed.json 时立刻刷新 runtime 缓存（原点位置/安全检查即时生效）
        try:
            bed_config_path = get_runtime()["paths"].get("bed_config")
            if bed_config_path is not None and target == Path(bed_config_path).resolve():
                reload_bed_data()
        except Exception:
            pass
        self._source_path = target
        self._modified = False
        self._refresh_title()
        self.saved.emit(str(target))
        return target

    def add_child_item(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return

        kind = item.data(0, ITEM_KIND_ROLE)
        if kind not in {"dict", "list"}:
            return

        child_kind = "value"
        child_key = "new_key"
        child_value = ""
        child_type = "str"

        if kind == "list":
            child_key = f"[{item.childCount()}]"

        child = self._create_item(child_key, child_value, child_kind, child_type)
        item.addChild(child)
        item.setExpanded(True)
        self._renumber_list_children(item)
        self._mark_modified()

    def add_sibling_item(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return

        parent = item.parent()
        if parent is None:
            return

        # 克隆当前 item
        sibling = self._clone_item(item)
        sibling.setText(0, item.text(0) + "_拷贝")
        parent.addChild(sibling)
        self._renumber_list_children(parent)
        self.tree.setCurrentItem(sibling)
        self._mark_modified()

    def _clone_item(self, item: QTreeWidgetItem) -> QTreeWidgetItem:
        """递归克隆 item 及其所有子节点"""
        key = item.text(0)
        value = item.text(1)
        type_name = item.text(2)
        kind = item.data(0, ITEM_KIND_ROLE)

        clone = self._create_item(key, value, kind, type_name)

        # 递归克隆子节点
        for i in range(item.childCount()):
            child = item.child(i)
            child_clone = self._clone_item(child)
            clone.addChild(child_clone)

        return clone

    def delete_current_item(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return

        parent = item.parent()
        if parent is None:
            return

        parent.removeChild(item)
        self._renumber_list_children(parent)
        self._mark_modified()

    def _refresh_title(self) -> None:
        if self._source_path is None:
            title = "JSON 对象"
        else:
            title = str(self._source_path)
        if self._modified:
            title = f"{title} *"
        self.title_label.setText(title)
        is_file_source = self._source_path is not None
        self.reload_button.setEnabled(is_file_source)
        self.save_button.setText("保存文件" if is_file_source else "导出保存")

    def _rebuild_tree(self) -> None:
        self._rebuilding = True
        self.tree.clear()

        if self._data is None:
            self._rebuilding = False
            return

        root = self._build_item("root", self._data)
        root.setText(0, self._root_title())
        root.setFlags((root.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsEditable)
        self.tree.addTopLevelItem(root)
        # 默认收到第一层：只展开根，第一层键可见但不展开（重载同样重置）
        self._expand_level = 1
        self._apply_expand_level()
        self._fit_columns()
        self._rebuilding = False

    @staticmethod
    def _item_depth(item: QTreeWidgetItem) -> int:
        depth = 0
        parent = item.parent()
        while parent is not None:
            depth += 1
            parent = parent.parent()
        return depth

    def _max_depth(self) -> int:
        max_depth = 0
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            max_depth = max(max_depth, self._item_depth(iterator.value()))
            iterator += 1
        return max_depth

    def _apply_expand_level(self) -> None:
        """按当前层级绝对设置每个容器节点的展开状态（与历史状态无关）。"""
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item.childCount():
                item.setExpanded(self._item_depth(item) < self._expand_level)
            iterator += 1
        self._update_level_buttons()

    def _set_expand_level(self, level: int) -> None:
        self._expand_level = max(0, min(level, self._max_depth() + 1))
        self._apply_expand_level()
        self._fit_columns()

    def _update_level_buttons(self) -> None:
        self.collapse_button.setEnabled(self._expand_level > 0)
        self.expand_button.setEnabled(self._expand_level < self._max_depth() + 1)

    def _fit_columns(self) -> None:
        for column in range(self.tree.columnCount()):
            self.tree.resizeColumnToContents(column)

    def _build_item(self, key: str, value: Any) -> QTreeWidgetItem:
        if isinstance(value, dict):
            item = self._create_item(key, f"{{{len(value)}}}", "dict", "dict")
            for child_key, child_value in value.items():
                item.addChild(self._build_item(str(child_key), child_value))
            return item

        if isinstance(value, list):
            item = self._create_item(key, f"[{len(value)}]", "list", "list")
            for index, child_value in enumerate(value):
                item.addChild(self._build_item(f"[{index}]", child_value))
            return item

        scalar_type = self._scalar_type_name(value)
        item = self._create_item(key, self._format_scalar(value), "value", scalar_type)
        return item

    def _create_item(self, key: str, value: str, kind: str, type_name: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([key, value, type_name])
        item.setData(0, ITEM_KIND_ROLE, kind)
        flags = item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if kind == "value":
            flags |= Qt.ItemIsEditable
        elif kind == "dict":
            flags |= Qt.ItemIsEditable
        item.setFlags(flags)
        return item

    def _root_title(self) -> str:
        return self._source_path.name if self._source_path is not None else "JSON"

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        del column
        if self._rebuilding:
            return

        kind = item.data(0, ITEM_KIND_ROLE)
        if kind == "value":
            if self._should_keep_string(item):
                self._rebuilding = True
                item.setText(2, "str")
                self._rebuilding = False
                self._sync_data_from_tree()
                self._mark_modified()
                return
            parsed = self._parse_scalar(item.text(1))
            item.setText(1, self._format_scalar(parsed))
            item.setText(2, self._scalar_type_name(parsed))
        elif kind in {"dict", "list"}:
            item.setText(1, self._container_summary(item))

        self._sync_data_from_tree()
        self._mark_modified()

    def _sync_data_from_tree(self) -> None:
        if self.tree.topLevelItemCount() == 0:
            self._data = {}
            return
        root = self.tree.topLevelItem(0)
        self._data = self._item_to_value(root)

    def _item_to_value(self, item: QTreeWidgetItem) -> Any:
        kind = item.data(0, ITEM_KIND_ROLE)
        if kind == "dict":
            result: dict[str, Any] = {}
            for index in range(item.childCount()):
                child = item.child(index)
                result[child.text(0)] = self._item_to_value(child)
            return result

        if kind == "list":
            return [self._item_to_value(item.child(index)) for index in range(item.childCount())]

        if self._should_keep_string(item):
            return item.text(1)
        return self._parse_scalar(item.text(1))

    def _should_keep_string(self, item: QTreeWidgetItem) -> bool:
        return item.text(0) in FORCE_STRING_KEYS or item.text(2) == "str"

    def _parse_scalar(self, text: str) -> Any:
        stripped = text.strip()
        if stripped == "":
            return ""
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return text

    def _format_scalar(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def _scalar_type_name(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int) and not isinstance(value, bool):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "str"
        return type(value).__name__

    def _container_summary(self, item: QTreeWidgetItem) -> str:
        kind = item.data(0, ITEM_KIND_ROLE)
        if kind == "dict":
            return f"{{{item.childCount()}}}"
        if kind == "list":
            return f"[{item.childCount()}]"
        return item.text(1)

    def _renumber_list_children(self, item: QTreeWidgetItem) -> None:
        if item.data(0, ITEM_KIND_ROLE) != "list":
            return
        self._rebuilding = True
        for index in range(item.childCount()):
            item.child(index).setText(0, f"[{index}]")
        item.setText(1, self._container_summary(item))
        self._rebuilding = False

    def _mark_modified(self) -> None:
        self._modified = True
        self._refresh_title()
        self.data_changed.emit(self.data())
