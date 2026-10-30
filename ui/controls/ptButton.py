from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from .pt_source import resolve_point


class PtButton(QFrame):
    """
    点动按钮：点击后把点位置 True，之后保持，由别处复位。

    用法与其它控件一样，只给点名，不用理会它在哪张表
    （内部经 pt_source 按名解析，写入只有 plc 支持）。

    reset_delay=True 时是带延时复位的点动：点击置 True 成功后
    2 秒自动再写 False（_RESET_DELAY_MS）。这 2 秒从点击写入完成
    开始算，用控件自己的单次 QTimer 计时，不阻塞界面；2 秒内
    再次点击会重新置 True 并重新计时满 2 秒。控件销毁时定时器
    随之销毁，未到点的复位不会再发出。

    reset_delay=False（默认）时就是普通置位按钮：点击置 True
    后一直保持，不自动复位，与 PtToggle 的保持语义分开——
    需要脉冲行为时才打开这个开关。
    """

    _COLOR_ON = "#ff0000"
    _COLOR_OFF = "#808080"
    _COLOR_ERR = "#ffd700"
    _READBACK_DELAY_MS = 1000
    _RESET_DELAY_MS = 2000

    def __init__(
        self,
        pt_name: str,
        reset_delay: bool = False,
        parent: QWidget | None = None,
        title: str = "",
    ) -> None:
        super().__init__(parent)
        self._pt_name = pt_name
        self._title_text = title or pt_name
        self._reset_delay = bool(reset_delay)

        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._auto_reset)

        self._setup_ui()
        self._set_state("err")
        self.setCursor(Qt.PointingHandCursor)

    def _setup_ui(self) -> None:
        self.setObjectName("ptButton")

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(4)
        root.setAlignment(Qt.AlignCenter)

        # 按钮本体：文字就是点名（或 title），点击置 True
        self._button = QPushButton(self._title_text, self)
        self._button.setObjectName("ptButtonPush")
        self._button.clicked.connect(self._on_click)
        root.addWidget(self._button)

        # 状态文字 ON/OFF/ERR，与 PtToggle 同口径
        self._status_label = QLabel("ERR", self)
        self._status_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self._status_label)

    def _set_state(self, state: str) -> None:
        """更新状态文字外观。state: on | off | err"""
        if state == "on":
            color, text = self._COLOR_ON, "ON"
        elif state == "off":
            color, text = self._COLOR_OFF, "OFF"
        else:
            color, text = self._COLOR_ERR, "ERR"
        self._status_label.setText(text)
        self._status_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def update(self) -> None:
        """按点名读取点位并更新状态显示（读不到显示 ERR）。"""
        try:
            resolved = resolve_point(self._pt_name)
            if resolved is None:
                self._set_state("err")
                return
            value = resolved.read()
            if value is None:
                self._set_state("err")
            else:
                self._set_state("on" if bool(value) else "off")
        except Exception:
            self._set_state("err")

    def _on_click(self) -> None:
        """点击置 True；reset_delay 打开时同时（重新）启动 2 秒复位计时。"""
        try:
            resolved = resolve_point(self._pt_name)
            if resolved is None:
                self._set_state("err")
                return
            # 写失败（点只读、通讯异常等）会抛错走 ERR，且不启动复位计时：
            # 本来就没有置成功，没有什么可复位的。
            resolved.write(True)
            if self._reset_delay:
                self._reset_timer.start(self._RESET_DELAY_MS)
            QTimer.singleShot(self._READBACK_DELAY_MS, self.update)
        except Exception:
            self._set_state("err")

    def _auto_reset(self) -> None:
        """2 秒到点：无条件写 False 并回读刷新。

        无条件写与 plc_batch 的复位口径一致：到点就清，不先读
        当前值。写失败按 ERR 显示，不再重试。
        """
        try:
            resolved = resolve_point(self._pt_name)
            if resolved is None:
                self._set_state("err")
                return
            resolved.write(False)
            QTimer.singleShot(self._READBACK_DELAY_MS, self.update)
        except Exception:
            self._set_state("err")
