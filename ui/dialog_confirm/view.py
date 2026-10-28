"""
流程步骤执行确认对话框

- 屏蔽直接关闭: 标题栏 X 按钮 + closeEvent 都被禁用
- 自定义按钮: "确认执行" (蓝色) / "中止流程" (红色)
- 非模态: 通过 finished 信号异步回调, 由调用方负责 deleteLater
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class ConfirmDialog(QDialog):
    """试验流程中节点执行前的人工确认对话框.

    行为约束:
    - 不允许用户通过标题栏关闭按钮直接关闭 (屏蔽 X + closeEvent 始终 ignore)
    - 必须通过 "确认执行" 或 "中止流程" 二选一返回结果
    - 非模态, 与主窗口可交互; 通过 finished 信号异步回调

    使用示例:
        dialog = ConfirmDialog("步骤A", "请确认...", parent)
        dialog.finished.connect(on_done)
        dialog.show()

    finished 信号参数:
    - QDialog.Accepted -> 用户点击 "确认执行"
    - QDialog.Rejected -> 用户点击 "中止流程" 或按下 Esc
    """

    def __init__(self, node_name: str, info: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("执行确认")
        # 关键: 屏蔽标题栏右上角 X 按钮
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(440, 220)
        self._build_ui(node_name, info)

    def _build_ui(self, node_name: str, info: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)

        # 主提示
        prompt = QLabel(self)
        prompt.setTextFormat(Qt.TextFormat.RichText)
        prompt.setWordWrap(True)
        prompt.setText(
            '<p style="font-size:18px; font-weight:bold; color:#d97706; margin:0;">'
            f'步骤 [{node_name}] 需要确认后继续执行。'
            '</p>'
        )
        layout.addWidget(prompt)

        # 附加信息 (若有)
        if info:
            extra_label = QLabel(self)
            extra_label.setTextFormat(Qt.TextFormat.RichText)
            extra_label.setWordWrap(True)
            extra_label.setText(
                '<p style="font-size:18px; color:#92400e; margin:0; '
                'background:#fef3c7; padding:8px 12px; border:1px solid #f59e0b; '
                'border-radius:4px;">'
                f'{info}'
                '</p>'
            )
            layout.addWidget(extra_label)

        # 询问
        ask_label = QLabel(self)
        ask_label.setTextFormat(Qt.TextFormat.RichText)
        ask_label.setText(
            '<p style="font-size:14px; color:#475569; margin:0; font-weight:bold;">'
            '是否继续执行？</p>'
        )
        layout.addWidget(ask_label)

        layout.addStretch(1)

        # 按钮区
        button_row = QHBoxLayout()
        button_row.setSpacing(12)

        # 中止流程 -> 红色
        self._abort_btn = QPushButton("中止流程", self)
        self._abort_btn.setMinimumHeight(44)
        self._abort_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._abort_btn.setStyleSheet(
            "QPushButton {"
            " background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #dc2626, stop:1 #b91c1c);"
            " color: white; border: none; border-radius: 6px;"
            " font-size: 15px; font-weight: 600; padding: 0 24px;"
            "}"
            "QPushButton:hover {"
            " background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #ef4444, stop:1 #dc2626);"
            "}"
            "QPushButton:pressed {"
            " background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #b91c1c, stop:1 #991b1b);"
            "}"
        )
        self._abort_btn.clicked.connect(self.reject)

        # 确认执行 -> 蓝色 (默认按钮)
        self._confirm_btn = QPushButton("确认执行", self)
        self._confirm_btn.setMinimumHeight(44)
        self._confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._confirm_btn.setDefault(True)
        self._confirm_btn.setAutoDefault(True)
        self._confirm_btn.setStyleSheet(
            "QPushButton {"
            " background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #2563eb, stop:1 #1d4ed8);"
            " color: white; border: none; border-radius: 6px;"
            " font-size: 15px; font-weight: 600; padding: 0 24px;"
            "}"
            "QPushButton:hover {"
            " background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #3b82f6, stop:1 #2563eb);"
            "}"
            "QPushButton:pressed {"
            " background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #1d4ed8, stop:1 #1e40af);"
            "}"
        )
        self._confirm_btn.clicked.connect(self.accept)

        button_row.addWidget(self._confirm_btn)
        button_row.addStretch(1)
        button_row.addWidget(self._abort_btn)
        layout.addLayout(button_row)

        self.setStyleSheet(
            "QDialog { background-color: #f8fafc; }"
            "QLabel { background: transparent; }"
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        """屏蔽直接关闭: 忽略所有 close 事件 (X / Alt+F4 / 系统菜单).

        弹窗只能通过 "确认执行" 或 "中止流程" 按钮返回结果.
        """
        event.ignore()