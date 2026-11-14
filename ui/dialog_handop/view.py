"""手动操作弹窗: 工具菜单 -> 手动操作.

两组上下排列的 [警示提醒 + toggle], 对应 plc 输出点 (BOOL):
- 返修工装允许
- 返修手动横移

toggle 用通用 PtToggle (点名调用, 点击翻转写入, 灰=OFF/红=ON/黄=ERR).
状态跟随 plc 轮询刷新: 订阅 broker plc_poll, 经 Qt Signal 转主线程刷
控件, 与 dialog_pts 同一机制, 不用页面自己的 QTimer.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from _runtime import get_runtime
from ui.controls import PtToggle

logger = logging.getLogger(__name__)

#: 每组内容: (警示标题, 警示正文, plc 点名)
_TOGGLES: tuple[tuple[str, str, str], ...] = (
    (
        "允许返修操作",
        "该功能开启后方可进行返修操作，返修完毕后必须关闭！",
        "允许返修工装",
    ),
    (
        "允许手动横移",
        "该功能开启 5 秒后，切换到手动方可进行横移操作，操作完毕后必须关闭！",
        "允许手动横移",
    ),
)

#: 警示提醒样式: 红字粗体 + 浅红底 + 红框, 要求醒目
_WARNING_STYLE = (
    "QLabel {"
    "  color: #b91c1c;"
    "  background-color: #fef2f2;"
    "  border: 2px solid #dc2626;"
    "  border-radius: 6px;"
    "  padding: 10px 12px;"
    "}"
)


class Window(QDialog):
    """工具 -> 手动操作: 返修/手动横移两个允许位的保持型开关."""

    _poll_signal = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("手动操作")
        self.setModal(True)
        self.resize(700, 300)
        self.runtime = get_runtime()

        self._poll_signal.connect(self._on_poll_update)
        self._toggles: list[PtToggle] = []
        self._broker_subscriptions: list[object] = []

        self._build_ui()
        self._subscribe()
        self._refresh_toggles()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        for title, warning, pt_name in _TOGGLES:
            row = QHBoxLayout()
            row.setSpacing(12)

            # 左侧警示提醒 (占满剩余宽度, 文字换行)
            label = QLabel(self)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(True)
            label.setStyleSheet(_WARNING_STYLE)
            label.setText(
                f"<div style='font-size: 17px; font-weight: bold;'>⚠ {title}</div>"
                f"<div style='font-size: 14px; font-weight: bold; margin-top: 4px;'>"
                f"{warning}</div>"
            )
            row.addWidget(label, 1)

            # 右侧 toggle (点名调用, 固定宽度不拉伸)
            toggle = PtToggle(pt_name, parent=self)
            toggle.setMinimumWidth(130)
            toggle.setMaximumWidth(130)
            self._toggles.append(toggle)
            row.addWidget(toggle, 0)

            layout.addLayout(row)

        layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _subscribe(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            return
        self._broker_subscriptions = [
            broker.subscribe("plc_poll", self._on_plc_poll),
        ]

    def _unsubscribe(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            self._broker_subscriptions.clear()
            return
        for subscription in self._broker_subscriptions:
            try:
                broker.unsubscribe(subscription)
            except Exception:  # noqa: BLE001 - 关闭时退订失败不阻断
                logger.exception("手动操作弹窗退订 plc_poll 失败")
        self._broker_subscriptions.clear()

    def _on_plc_poll(self, **payload) -> None:
        # broker 回调跑在轮询线程上, 经 Signal 转到主线程再刷控件
        self._poll_signal.emit(dict(payload))

    @Slot(dict)
    def _on_poll_update(self, _payload: dict) -> None:
        self._refresh_toggles()

    def _refresh_toggles(self) -> None:
        for toggle in self._toggles:
            toggle.update()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._refresh_toggles()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._unsubscribe()
        super().closeEvent(event)
