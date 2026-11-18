"""插件演示: 只读展示运行状态, 不写任何硬件点, 可放心在真机上打开.

插件契约 (见 libs/plugin_loader.py):
    TITLE: 菜单名; ADMIN_ONLY: 仅管理员可打开; Window: 零参 QDialog 子类.
运行时数据一律用 get_runtime() 自取, 与现有弹窗写法一致.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from _runtime import get_runtime

TITLE = "插件演示"
ADMIN_ONLY = False


def _read_point(plc, name: str) -> str:
    """读一个 PLC 点, 任何异常都只显示占位, 不抛错."""
    if plc is None:
        return "-"
    try:
        value = plc.read(name)
    except Exception:
        return "读取失败"
    return "-" if value is None else str(value)


class Window(QDialog):
    """只读演示弹窗: 当前用户 + PLC 状态 + 几个实时点."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._user_label = QLabel("-")
        self._plc_label = QLabel("-")
        self._auto_label = QLabel("-")
        self._p1_label = QLabel("-")
        self._p2_label = QLabel("-")
        form.addRow("当前用户:", self._user_label)
        form.addRow("PLC 状态:", self._plc_label)
        form.addRow("自动:", self._auto_label)
        form.addRow("加载压力1:", self._p1_label)
        form.addRow("加载压力2:", self._p2_label)
        layout.addLayout(form)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh)
        layout.addWidget(refresh_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._refresh()

    def _refresh(self) -> None:
        runtime = get_runtime()
        self._user_label.setText(str(runtime.get("current_user") or "-"))
        plc = runtime.get("plc")
        if plc is None:
            self._plc_label.setText("未启用")
        else:
            alive = getattr(plc, "alive", None)
            if alive is True:
                self._plc_label.setText("在线")
            elif alive is False:
                self._plc_label.setText("离线")
            else:
                self._plc_label.setText("已创建")
        self._auto_label.setText(_read_point(plc, "自动"))
        self._p1_label.setText(_read_point(plc, "加载压力1"))
        self._p2_label.setText(_read_point(plc, "加载压力2"))
