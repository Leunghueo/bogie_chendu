from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget
from ui.wgt_gflow._view import Ui_Form

_CHIP_HEIGHT = 41
_CHIP_MIN_HEIGHT = 20
_CHIP_SPACING = 10


def _parse_gnode(gnode: str) -> tuple[str, int] | None:
    """把 node 的 gnode 解析为 (区域键, 区域内序号), 与 _view.ui 里的 garea_* 容器对应.

    约定 (与改造前的定点 label 编号完全一致, workflow JSON 无需改动):
    - ``gnode_head`` / ``gnode_end``: 专用单节点区域;
    - 一位数字 (``gnode_1`` .. ``gnode_9``): 顶部主列区域 ``top``, 序号即该数字;
    - 两位及以上数字: 首位是区域号 (``gnode_201`` -> 区域 ``2``), 其余是区域内序号 (01).
    其余形式返回 None. gnode 为空或区域不存在时该 node 只不显示, 不影响 workflow 本身.
    """
    if not gnode or not gnode.startswith("gnode_"):
        return None
    suffix = gnode[len("gnode_"):]
    if suffix in ("head", "end"):
        return suffix, 0
    if suffix.isdigit():
        if len(suffix) == 1:
            return "top", int(suffix)
        return suffix[0], int(suffix[1:])
    return None


class FlowGraph(QWidget):
    """流程示意图: _view.ui 只定义区域容器 (garea_*), 区域内的节点 chip 运行时按
    workflow 动态生成. 某个区域里没有节点时不留空框, 节点数变化只影响本区域的排列.
    """

    def __init__(self) -> None:
        super().__init__()
        # 设置 size policy 为 Expander，允许自适应缩放
        size_policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setSizePolicy(size_policy)
        self.graph: Ui_Form | None = None
        self._regions: dict[str, QVBoxLayout] = {}
        self._chips: dict[str, QLabel] = {}
        self._signature: tuple | None = None
        self._build_empty_ui()

    def _build_ui(self) -> None:
        layout = self.layout()
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.graph = Ui_Form()
        self.graph.setupUi(self.graph)
        layout.addWidget(self.graph)

        self._regions = {}
        self._chips = {}
        self._signature = None
        for area in self.graph.findChildren(QWidget):
            name = area.objectName()
            if not name.startswith("garea_"):
                continue
            region_layout = QVBoxLayout(area)
            region_layout.setContentsMargins(0, 0, 0, 0)
            region_layout.setSpacing(_CHIP_SPACING)
            region_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            self._regions[name[len("garea_"):]] = region_layout

    def _build_empty_ui(self) -> None:
        """Build the placeholder displayed when no flow graph is available."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.empty_label = QLabel("请在左侧创建实验工单", self)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet('color: darkblue;\nfont: 30pt "Microsoft YaHei UI";')
        layout.addWidget(self.empty_label)

    def update(self, workflow) -> None:
        """根据 workflow 的节点更新示意图.

        节点集合 (id/gnode/名称) 没变时只刷新已有 chip 的文字与状态色;
        变了才按区域重建 chip. gnode 为空的节点不生成 chip.
        """
        if self.graph is None:
            self._build_ui()
        from wf import WorkflowState

        color_map = {
            WorkflowState.IDLE: "#E8E8E8",
            WorkflowState.RUNNING: "#90EE90",
            WorkflowState.ERROR: "#FF6B6B",
            WorkflowState.STOPPED: "#FFF8E1",
        }

        if workflow is None or not hasattr(workflow, 'nodes'):
            return

        entries: list[tuple[str, int, int, object]] = []
        for seq, node in enumerate(workflow.nodes.values()):
            parsed = _parse_gnode(getattr(node, 'gnode', '') or '')
            if parsed is None:
                continue
            region, order = parsed
            if region not in self._regions:
                continue
            entries.append((region, order, seq, node))

        signature = tuple(sorted(
            (node.node_id, region, order, node.node_name)
            for region, order, _, node in entries
        ))
        if signature != self._signature:
            self._rebuild_chips(entries)
            self._signature = signature

        for _, _, _, node in entries:
            chip = self._chips.get(node.node_id)
            if chip is None:
                continue
            chip.setText(node.node_name)
            state = getattr(node, 'state', WorkflowState.IDLE)
            bg_color = color_map.get(state, "#E8E8E8")
            chip.setStyleSheet(
                f"color: rgb(0, 0, 0);"
                f"border: 1px solid;"
                f"border-radius: 8px;"
                f"background-color: {bg_color};"
            )

    def _rebuild_chips(self, entries: list[tuple[str, int, int, object]]) -> None:
        for region_layout in self._regions.values():
            while region_layout.count():
                item = region_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        self._chips = {}

        grouped: dict[str, list[tuple[int, int, object]]] = {}
        for region, order, seq, node in entries:
            grouped.setdefault(region, []).append((order, seq, node))

        for region, items in grouped.items():
            region_layout = self._regions[region]
            items.sort(key=lambda entry: (entry[0], entry[1]))
            area = region_layout.parentWidget()
            avail = area.height() if area is not None else _CHIP_HEIGHT
            count = len(items)
            if count == 1:
                chip_height = min(_CHIP_HEIGHT, max(_CHIP_MIN_HEIGHT, avail))
            else:
                fit = (avail - (count - 1) * _CHIP_SPACING) // count
                chip_height = max(_CHIP_MIN_HEIGHT, min(_CHIP_HEIGHT, fit))
            for _, _, node in items:
                chip = QLabel(node.node_name)
                chip.setObjectName(f"chip_{node.node_id}")
                chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
                chip.setWordWrap(True)
                chip.setFixedHeight(int(chip_height))
                region_layout.addWidget(chip)
                self._chips[node.node_id] = chip
