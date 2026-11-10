from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,

    QVBoxLayout,
    QWidget,
)

from ui.controls import PtButton, PtLed, PtToggle

logger = logging.getLogger(__name__)


LIMIT = 5

class StatusDashboard(QFrame):
    """PLC 实时状态 Dashboard: 复用 ui.controls.PtLed 显示点位, 前置防沉降气缸点动按钮."""

    # 每行 = [组1, 组2, ...], 每组内为 (pt_name, 显示标题); 组间插入分隔线; 标题为空串时直接显示点位名
    _LED_ROWS: list[list[list[tuple[str, str]]]] = [
        # 第一行: 模式 / 加载压力 / 加载头位移
        [
            [("手动", ""), ("自动", "")],
            [("加载压力1", ""), ("加载压力2", "")],
            [("加载头垂向位移1", "压头垂向1"), ("加载头垂向位移2", "压头垂向2")],
            [("压头横向1", "压头水平1"), ("压头横向2", "压头水平2")],
            [("气压采集1", "气压1"), ("气压采集2", "气压2")],
        ],
        
        # 第二行: 车轮位移 / 车轮内侧距 / 导轨高
        # [
        #     [
        #         ("称重台位移1", "车轮位移1"),
        #         ("称重台位移2", "车轮位移2"),
        #         ("称重台位移3", "车轮位移3"),
        #         ("称重台位移4", "车轮位移4"),
        #     ],
        #     [
        #         ("内测距激光1", "车轮内测距1"),
        #         ("内测距激光2", "车轮内测距2"),
        #         ("内测距激光3", "车轮内测距3"),
        #         ("内测距激光4", "车轮内测距4"),
        #     ],
        #     [
        #         ("轮高激光1", "轮高1"),
        #         ("轮高激光2", "轮高2"),
        #         ("轮高激光3", "轮高3"),
        #         ("轮高激光4", "轮高4"),
        #     ],
        # ],
    ]

    # 需要显示相对位移的点位及其在 bed.json「原点位置」中的基准键: 显示值 = 原始值 - 基准值
    # 键必须是 _LED_ROWS 里实际显示的点名:
    #   第二行第一组是 CAN 点 称重台位移1~4 -> 减 滑台位移N
    #   第二行第二组是 VSP 点 内测距激光1~4 -> 减 滑台内测距N
    _RELATIVE_POS_OFFSETS: dict[str, str] = {
        "称重台位移1": "滑台位移1",
        "称重台位移2": "滑台位移2",
        "称重台位移3": "滑台位移3",
        "称重台位移4": "滑台位移4",
        "内测距激光1": "滑台内测距1",
        "内测距激光2": "滑台内测距2",
        "内测距激光3": "滑台内测距3",
        "内测距激光4": "滑台内测距4",
    }

    # 防沉降气缸点动按钮: (显示标题, plc 点位名)
    _PT_BUTTONS: list[tuple[str, str]] = [
        ("防沉开", "防沉降气缸伸出"),
        ("防沉关", "防沉降气缸收回"),
    ]
    #: True = 点动脉冲(置 True 后 2 秒自动写 False); False = 点一下就一直保持
    _PT_BUTTON_RESET_DELAY = True

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusDashboard")
        self.setStyleSheet(
            """
            #statusDashboard {
                border : 2px solid gray;
                border-radius: 6px;
                padding: 4px;
            }
            """
        )
        self._setup_ui()

    def _setup_ui(self) -> None:

        def vline() -> QFrame:
            _vline = QFrame(self)
            _vline.setFrameShape(QFrame.VLine)
            _vline.setFrameShadow(QFrame.Sunken)
            # 关键：border-left 做垂直线，关闭其他边框
            _vline.setStyleSheet("""
            QFrame[frameShape="5"]{
                border: none;
                border-left: 1px solid #334155;
            }
            """)
            return _vline

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)


        # 中间: 上下两行点位数据
        data_column = QVBoxLayout()
        data_column.setSpacing(6)

        self._leds: list[PtLed] = []
        for row_groups in self._LED_ROWS:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setAlignment(Qt.AlignVCenter)
            for group_index, group in enumerate(row_groups):
                for pt_name, title in group:
                    # 在 _RELATIVE_POS_OFFSETS 里的点位由控件自己减基准值, 显示相对位移
                    led = PtLed(
                        pt_name,
                        parent=self,
                        title=title,
                        base_key=self._RELATIVE_POS_OFFSETS.get(pt_name, ""),
                        limit=LIMIT,
                    )
                    self._leds.append(led)
                    row.addWidget(led)
                if group_index < len(row_groups) - 1:
                    row.addWidget(vline())
            row.addStretch(1)
            data_column.addLayout(row)
        data_column.addStretch(1)

        layout.addLayout(data_column, 1)

        # 最前: 防沉降气缸点动按钮（上下排列，尽量少占宽度）
        button_col = QVBoxLayout()
        button_col.setSpacing(4)
        button_col.setAlignment(Qt.AlignVCenter)
        self._pt_buttons: list[PtButton] = []
        for title, pt_name in self._PT_BUTTONS:
            button = PtButton(
                pt_name,
                reset_delay=self._PT_BUTTON_RESET_DELAY,
                parent=self,
                title=title,
            )
            button.setFixedWidth(76)
            self._pt_buttons.append(button)
            button_col.addWidget(button)
        layout.addLayout(button_col, 0)
        layout.addWidget(vline(), 0)


    def refresh_data(self) -> None:
        """刷新所有点位显示（由 plc_poll 信号触发，在主线程执行）"""
        for button in self._pt_buttons:
            button.update()
        for led in self._leds:
            led.update()

