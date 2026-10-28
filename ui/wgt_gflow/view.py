from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget
from ui.wgt_gflow._view import Ui_Form


class FlowGraph(QWidget):
    def __init__(self) -> None:
        super().__init__()
        # 设置 size policy 为 Expander，允许自适应缩放
        size_policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setSizePolicy(size_policy)
        self._build_empty_ui()

    def _build_ui(self) -> None:
        layout=self.layout()
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            else:
                sub_layout = item.layout()
                if sub_layout is not None:
                    clear_layout(sub_layout)

        self.graph = Ui_Form()
        self.graph.setupUi(self.graph)

        for label in self.graph.findChildren(QLabel):
            if label.objectName().startswith("gnode"):
                label.setText(label.objectName())

        layout.addWidget(self.graph)

    def _build_empty_ui(self) -> None:
        """Build the placeholder displayed when no flow graph is available."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.empty_label = QLabel("请在左侧创建实验工单", self)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet('color: darkblue;\nfont: 30pt "Microsoft YaHei UI";')
        layout.addWidget(self.empty_label)

    def update(self, workflow) -> None:
        '''
        这是一个通过`workflow数据`更新`FlowGraph`控件样式的方法,同时也是该控件的**核心功能**
        具体逻辑如下:
        1. 传递进来的`workflow`包含了流程的所有节点实例.每个实例都有一个`gnode`字段.
        2. 如果`gnode`非空, 例如"gnode_101", 那么查找`objectName==gnode_101`的控件, 并**根据node实例更新该QLabel的样式**,具体如下:
            3.1 将该QLabel的text设置为`该node的node_name`;
            3.2 获取该node实例的`state`, 并设置QLabel的背景色(IDLE/DONE为灰色, RUNNING为绿色, ERROR为红色)
        3. 如果`gnode`为其他 则跳过;
        注意: 该方法的触发时机为`view_home`页面的`workflow`的每次节点状态变化.
        请完成该方法.
        '''
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

        for node in workflow.nodes.values():
            gnode_name = getattr(node, 'gnode', '')
            if not gnode_name:
                continue

            label = self.graph.findChild(QLabel, gnode_name)
            if label is None:
                continue

            label.setText(node.node_name)

            state = getattr(node, 'state', WorkflowState.IDLE)
            bg_color = color_map.get(state, "#E8E8E8")
            label.setStyleSheet(
                f"color: rgb(0, 0, 0);"
                f"border: 1px solid;"
                f"border-radius: 8px;"
                f"background-color: {bg_color};"
            )
