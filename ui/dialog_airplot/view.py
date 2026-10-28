"""空簧保压与差压试验监视页面。"""
from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QSizePolicy, QVBoxLayout, QWidget,
)

try:
    import pyqtgraph as pg
except ImportError:
    pg = None

from _runtime import get_runtime


class ChartWidget(QWidget):
    """同一时间轴上的两路气压曲线。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._times: list[float] = []
        self._pressures: list[list[float]] = [[], []]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if pg is None:
            label = QLabel("pyqtgraph 未安装，无法显示气压曲线", self)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("background: #0b0d0c; color: white;")
            layout.addWidget(label)
            return

        self._plot = pg.PlotWidget(self, background="#0b0d0c")
        self._plot.setLabel("left", "空气压力", units="kPa")
        self._plot.setLabel("bottom", "保压时间", units="min")
        self._plot.showGrid(x=True, y=True, alpha=0.45)
        self._plot.getAxis("left").setPen("#e5e7eb")
        self._plot.getAxis("bottom").setPen("#e5e7eb")
        self._plot.getAxis("left").setTextPen("#e5e7eb")
        self._plot.getAxis("bottom").setTextPen("#e5e7eb")
        self._plot.setXRange(0, 15, padding=0)
        self._plot.setYRange(0, 600)
        self._curves = [
            self._plot.plot(pen=pg.mkPen("#f2e65c", width=2)),
            self._plot.plot(pen=pg.mkPen("#f45b5b", width=2)),
        ]
        layout.addWidget(self._plot, 1)
        legend = QHBoxLayout()
        for color, name in (("#f2e65c", "空气弹簧1气压"), ("#f45b5b", "空气弹簧2气压")):
            item = QLabel(f'<span style="color:{color}">━━</span> {name}', self)
            item.setStyleSheet("color: #000000; padding: 3px 16px;")
            legend.addWidget(item)
        legend.addStretch()
        layout.addLayout(legend)

    def clear(self, duration: float) -> None:
        self._times.clear()
        for index in range(2):
            self._pressures[index].clear()
            if pg is not None:
                self._curves[index].setData([], [])
        if pg is not None:
            self._plot.setXRange(0, max(1.0, duration / 60), padding=0)
            # Y 轴固定 0-600, 不随数据自动缩放

    def append_data(self, elapsed: float, pressure1: float, pressure2: float) -> None:
        self._times.append(elapsed / 60)
        for index, pressure in enumerate((pressure1, pressure2)):
            self._pressures[index].append(pressure)
            if pg is not None:
                self._curves[index].setData(self._times, self._pressures[index])
        if pg is not None and self._times[-1] > self._plot.viewRange()[0][1]:
            self._plot.setXRange(0, self._times[-1] + 1, padding=0)


class Window(QWidget):
    """流程驱动的三类气压试验状态视图。"""

    message_received = Signal(dict)
    page_cleared = Signal()
    TRIALS = ("空簧保压", "差压1->2", "差压2->1")
    PRESSURE_KEYS = ("气压采集1", "气压采集2")
    LOAD_KEYS = ("加载头垂向位移1", "加载头垂向位移2", "加载压力1", "加载压力2")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = get_runtime()
        self._enabled = False
        self._trial_type: str | None = None
        self._workflow_id: str | None = None
        self._capture_start = 0.0
        self._starts: dict[str, tuple[float, float]] = {}
        self._ends: dict[str, tuple[float, float]] = {}
        self._load_start: dict[str, float | None] = {}
        self._latest: tuple[float, float] | None = None
        self._subscriptions: list[Any] = []
        self._cards: dict[str, QFrame] = {}
        self.setObjectName("airplotDialog")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setup_ui()
        self.message_received.connect(self._handle_message)
        self.page_cleared.connect(self._clear_page)
        broker = self.runtime.get("broker")
        if broker is not None:
            self._subscriptions = [
                broker.subscribe("enable_plot", lambda **payload: self.message_received.emit({"topic": "enable_plot", **payload})),
                broker.subscribe("clear_page", lambda **payload: self.page_cleared.emit()),
            ]
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._refresh)
        self._update_timer.start(1000)

    def _setup_ui(self) -> None:
        self.setStyleSheet("""
            QWidget#airplotDialog { background: #eceff1; color: #24313b; }
            QFrame#airplotCard { background: #f8fafb; border: 1px solid #bac7cc; border-radius: 6px; }
            /* 激活卡片: 蓝色描边 + 标题与数值加粗变蓝, 反向突出当前试验 */
            QFrame#airplotCard[active="true"] { border: 2px solid #1565c0; }
            QFrame#airplotCard[active="true"] QLabel#airplotCardTitle {
                font-weight: bold; color: #1565c0;
            }
            QFrame#airplotCard[active="true"] QLabel#airplotValue {
                font-weight: bold; color: #1565c0;
            }
            QLabel#airplotValue { background: #edf3f1; border: 1px solid #bfd0c9;
                border-radius: 3px; padding: 3px 6px; min-width: 65px; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        load_card, load_layout = self._card("加载数据（初始 / 当前）")
        load_grid = QGridLayout()
        load_grid.setHorizontalSpacing(8)
        load_grid.setVerticalSpacing(4)
        self._load_labels: dict[str, QLabel] = {}
        for index, (text, unit) in enumerate((
            ("垂向位移①（初始/当前）", "mm"), ("垂向位移②（初始/当前）", "mm"),
            ("加载力①（初始/当前）", "kN"), ("加载力②（初始/当前）", "kN"),
        )):
            row, col = divmod(index, 2)
            base = col * 4
            load_grid.addWidget(QLabel(text), row, base)
            for offset, title in enumerate(("试验前加载数据", "当前加载数据")):
                field = QLabel("—")
                field.setObjectName("airplotValue")
                field.setAlignment(Qt.AlignCenter)
                field.setToolTip("初始值" if offset == 0 else "当前值")
                self._load_labels[f"{title}:{index}"] = field
                load_grid.addWidget(field, row, base + offset + 1)
            unit_label = QLabel(unit)
            unit_label.setFixedWidth(26)
            load_grid.addWidget(unit_label, row, base + 3)
            load_grid.setColumnStretch(base + 1, 1)
            load_grid.setColumnStretch(base + 2, 1)
        load_layout.addLayout(load_grid)
        root.addWidget(load_card)

        chart_card, chart_layout = self._card("空气弹簧气压曲线")
        self._status_label = QLabel("当前试验：未开始")
        chart_layout.addWidget(self._status_label)
        self._chart = ChartWidget(chart_card)
        chart_layout.addWidget(self._chart, 1)
        root.addWidget(chart_card, 1)

        trial_row = QHBoxLayout()
        # 各试验卡片展示的字段; 三张卡均不含"试验结论"与"初始差压"
        field_names: dict[str, tuple[str, ...]] = {
            "空簧保压": ("空簧1初始气压", "空簧2初始气压", "空簧1保压后气压",
                     "空簧2保压后气压", "空簧1泄漏量", "空簧2泄漏量"),
            "差压1->2": ("空簧1气压", "空簧2气压", "当前差压"),
            "差压2->1": ("空簧1气压", "空簧2气压", "当前差压"),
        }
        self._fields: dict[str, dict[str, QLabel]] = {}
        for trial in self.TRIALS:
            card, layout = self._card(trial)
            self._cards[trial] = card
            self._fields[trial] = {}
            names = field_names[trial]
            grid = QGridLayout()
            grid.setHorizontalSpacing(4)
            grid.setVerticalSpacing(4)
            # "当前差压"独占一行, 值控件横向拉伸占满卡片宽度
            regular = [name for name in names if name != "当前差压"]
            for index, name in enumerate(regular):
                row, col = divmod(index, 2)
                base = col * 3
                value = QLabel("—")
                value.setObjectName("airplotValue")
                self._fields[trial][name] = value
                grid.addWidget(QLabel(name), row, base)
                grid.addWidget(value, row, base + 1)
                unit_label = QLabel("kPa")
                unit_label.setFixedWidth(28)
                grid.addWidget(unit_label, row, base + 2)
                grid.setColumnStretch(base + 1, 1)
            if "当前差压" in names:
                row = (len(regular) + 1) // 2
                value = QLabel("—")
                value.setObjectName("airplotValue")
                self._fields[trial]["当前差压"] = value
                grid.addWidget(QLabel("当前差压"), row, 0)
                grid.addWidget(value, row, 1, 1, 4)
                unit_label = QLabel("kPa")
                unit_label.setFixedWidth(28)
                grid.addWidget(unit_label, row, 5)
                grid.setColumnStretch(4, 1)
            layout.addLayout(grid)
            trial_row.addWidget(card, 1)
        root.addLayout(trial_row)



    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(self)
        card.setObjectName("airplotCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        title_label = QLabel(title)
        title_label.setObjectName("airplotCardTitle")
        layout.addWidget(title_label)
        return card, layout

    def _current_workflow(self) -> Any:
        return self.runtime.get("wf")

    def _process_data(self) -> dict[str, Any]:
        """workflow.data["过程数据"], 缺失时自动创建."""
        workflow = self._current_workflow()
        data = getattr(workflow, "data", {})
        if not isinstance(data, dict):
            return {}
        process = data.get("过程数据")
        if not isinstance(process, dict):
            process = data.setdefault("过程数据", {})
        return process

    def _read_values(self, names: tuple[str, ...]) -> list[float | None]:
        plc = self.runtime.get("plc")
        if plc is None:
            return [None] * len(names)
        values: list[float | None] = []
        for name in names:
            try:
                value = plc.read(name)
                values.append(float(value) if value is not None else None)
            except (KeyError, IOError, OSError, TypeError, ValueError):
                values.append(None)
        return values

    def _matches_workflow(self, payload: dict[str, Any]) -> bool:
        workflow = self._current_workflow()
        return workflow is not None and str(getattr(workflow, "id", "")) == str(payload.get("workflow_id", ""))

    def _update_card_states(self) -> None:
        """根据当前激活的试验切换三张卡片的高亮状态.

        - 激活卡片: 蓝色粗体描边 + 标题/数值加粗变蓝, 反向突出当前试验
        - 非激活卡片: 保持默认外观
        - 尚未开始任何试验时: 三张卡片均无高亮
        """
        # 试验已停止 (_enabled=False) 时, 全部卡片熄灭, 不再保留任何高亮
        active = self._trial_type if self._enabled else None
        for trial, card in self._cards.items():
            is_active = trial == active
            card.setProperty("active", "true" if is_active else "false")
            # 重新计算 QSS 选择器 (动态属性变化需 unpolish + polish)
            card.style().unpolish(card)
            card.style().polish(card)

    @Slot()
    def _clear_page(self) -> None:
        """收到 clear_page 消息后清空本页全部试验数据 (图表 / 文本框 / 缓存).

        仅重置页面显示状态, 不触碰工作流数据; 工作流再次下发 enable_plot 时重新开始记录.
        """
        self._enabled = False
        self._trial_type = None
        self._workflow_id = None
        self._capture_start = 0.0
        self._starts.clear()
        self._ends.clear()
        self._load_start.clear()
        self._latest = None
        # 加载数据 (试验前 / 当前)
        for field in self._load_labels.values():
            field.setText("—")
        # 三张试验卡片: 清空数值并清除超限红色背景
        for fields in self._fields.values():
            for field in fields.values():
                field.setText("—")
                field.setStyleSheet("")
        self._chart.clear(900)
        self._status_label.setText("当前试验：未开始")
        self._update_card_states()

    @Slot(dict)
    def _handle_message(self, payload: dict[str, Any]) -> None:
        if not self._matches_workflow(payload):
            return
        trial = payload.get("trial_type")
        if trial not in self.TRIALS:
            return
        self._trial_type = trial
        self._workflow_id = str(payload["workflow_id"])
        enabled = payload.get("enabled") is True
        if enabled:
            self._enabled = True
            self._capture_start = time.monotonic()
            self._ends.pop(trial, None)
            self._starts.pop(trial, None)
            self._latest = None
            self._load_start = dict(zip(self.LOAD_KEYS, self._read_values(self.LOAD_KEYS)))
            for field in self._fields[trial].values():
                field.setText("—")
                field.setStyleSheet("")  # 清除上一轮的超限红色背景
            self._chart.clear(900)
            readings = self._read_values(self.PRESSURE_KEYS)
            if all(value is not None for value in readings):
                self._starts[trial] = (readings[0], readings[1])
                self._chart.append_data(0, readings[0], readings[1])
            if trial == "空簧保压":
                # 过程数据: 试验开始时清空数组并写入首点 (差压试验不记录)
                process = self._process_data()
                process["空簧气压1"] = [readings[0]] if readings[0] is not None else []
                process["空簧气压2"] = [readings[1]] if readings[1] is not None else []
        else:
            readings = self._read_values(self.PRESSURE_KEYS)
            if all(value is not None for value in readings):
                self._ends[trial] = (readings[0], readings[1])
        self._update_card_states()
        # 末态显示: enable=false 时先存好 _ends, 此时 _enabled 仍为 True,
        # 走一次完整刷新让卡片显示收尾数据(初值/收尾压/泄漏量/差压)
        self._refresh()
        if not enabled:
            self._enabled = False
            # 关闭后熄灭高亮: _update_card_states 在 _enabled=False 时不再点亮任何卡片
            self._update_card_states()

    @staticmethod
    def _text(value: Any) -> str:
        try:
            return f"{float(value):.2f}" if value is not None else "—"
        except (TypeError, ValueError):
            return "—"

    @staticmethod
    def _apply_limit_style(field: QLabel, value: float | None, limits: Any) -> None:
        """数值异常(超限 / 读不到 / limits 缺失或非法)显红色, 数值正常显绿色."""
        _RED = "background: #e53935; border-color: #b71c1c; color: #ffffff;"
        _GREEN = "background: #2e7d32; border-color: #1b5e20; color: #ffffff;"
        over = True  # 读不到值 / limits 异常时, 一律视作异常
        if value is not None and isinstance(limits, dict):
            try:
                low = limits.get("最小值")
                high = limits.get("最大值")
                if low is not None or high is not None:
                    over = False
                    if low is not None and value < float(low):
                        over = True
                    if high is not None and value > float(high):
                        over = True
            except (TypeError, ValueError):
                over = True
        field.setStyleSheet(_RED if over else _GREEN)

    def _refresh(self) -> None:
        workflow = self._current_workflow()
        if self._workflow_id and str(getattr(workflow, "id", "")) != self._workflow_id:
            self._enabled = False
            self._trial_type = None
            self._workflow_id = None
            self._starts.clear()
            self._ends.clear()
            self._load_start.clear()
            self._latest = None
            self._chart.clear(900)
            self._update_card_states()
        state = getattr(getattr(workflow, "state", None), "value", None)
        if state in ("stopped", "done", "error"):
            self._enabled = False
        trial = self._trial_type
        if workflow is None:
            info = "未开始"
        else:
            meta = getattr(workflow, "meta", {}) or {}
            info = (
                f"车型:{meta.get('车型', '')}-"
                f"车号:{meta.get('车号', '')}-"
                f"位号:{meta.get('位号', '')}"
            )
        self._status_label.setText(f"当前试验：{info}")
        values = self._read_values(self.LOAD_KEYS)
        for index, value in enumerate(values):
            self._load_labels[f"当前加载数据:{index}"].setText(self._text(value))
            self._load_labels[f"试验前加载数据:{index}"].setText(self._text(self._load_start.get(self.LOAD_KEYS[index])))

        readings = self._read_values(self.PRESSURE_KEYS)
        if all(value is not None for value in readings):
            self._latest = readings[0], readings[1]
            if self._enabled:
                self._chart.append_data(time.monotonic() - self._capture_start, *self._latest)
                if self._trial_type == "空簧保压":
                    # 采样值写入工作流过程数据 (差压试验不记录)
                    process = self._process_data()
                    process.setdefault("空簧气压1", []).append(readings[0])
                    process.setdefault("空簧气压2", []).append(readings[1])
        if trial and self._enabled and self._latest:
            # 只刷新当前激活试验对应的卡片; 其他试验卡片(含非激活差压方向)不会被触碰
            fields = self._fields.get(trial)
            if fields is None:
                return
            start = self._starts.get(trial)
            end = self._ends.get(trial)
            results = getattr(workflow, "data", {}).get("结果数据", {})
            if trial == "空簧保压":
                for index in (0, 1):
                    number = index + 1
                    pressure = results.get(f"空气弹簧{number}初始气压", {})
                    initial = start[index] if start else pressure.get("测量值")
                    fields[f"空簧{number}初始气压"].setText(self._text(initial))
                    fields[f"空簧{number}保压后气压"].setText(self._text(end[index] if end else self._latest[index]))
                    compare = end[index] if end else self._latest[index]
                    leak = start[index] - compare if start else None
                    fields[f"空簧{number}泄漏量"].setText(self._text(leak))
                    # 泄漏量超出 [最小值, 最大值] 时红色背景提示
                    self._apply_limit_style(
                        fields[f"空簧{number}泄漏量"], leak,
                        results.get(f"空气弹簧{number}漏气量"),
                    )
            else:
                for index in (0, 1):
                    fields[f"空簧{index + 1}气压"].setText(self._text(self._latest[index]))
                sign = 1 if trial == "差压1->2" else -1
                diff = sign * (self._latest[0] - self._latest[1])
                fields["当前差压"].setText(self._text(diff))
                # 当前差压超出 [最小值, 最大值] 时红色背景提示
                limit_key = "差压阀试验值1" if trial == "差压1->2" else "差压阀试验值2"
                self._apply_limit_style(fields["当前差压"], diff, results.get(limit_key))

    def closeEvent(self, event: Any) -> None:
        self._update_timer.stop()
        broker = self.runtime.get("broker")
        if broker is not None:
            for subscription in self._subscriptions:
                broker.unsubscribe(subscription)
        self._subscriptions.clear()
        super().closeEvent(event)
