from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
from datetime import datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QEvent, QObject, QThread, Qt, Signal, QTimer, Slot
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from _runtime import bed_section, get_runtime
from libs import jobstore
from wf import NodeStoppedError, WorkflowState
from ui.controls import PtButton, PtLed
from ui.dialog_confirm.view import ConfirmDialog
from ui.dialog_result.view import ResultDialog
from ui.wgt_gflow.view import FlowGraph


logger = logging.getLogger(__name__)

LIMIT = 5

class StatusDashboard(QFrame):
    """PLC 实时状态 Dashboard: 复用 ui.controls.PtLed 显示点位, 前置防沉降气缸点动按钮, 尾部紧急停止按钮."""

    # 每行 = [组1, 组2, ...], 每组内为 (pt_name, 显示标题); 组间插入分隔线; 标题为空串时直接显示点位名
    _LED_ROWS: list[list[list[tuple[str, str]]]] = [
        # 第一行: 模式 / 加载压力 / 加载头位移
        [
            [("手动", ""), ("自动", "")],
            [("加载压力1", ""), ("加载压力2", "")],
            [("加载头垂向位移1", "压头位移1"), ("加载头垂向位移2", "压头位移2")],
            [("气压采集1", "气压1"), ("气压采集2", "气压2")],
        ],
        
        # 第二行: 车轮位移 / 车轮内侧距 / 导轨高
        [
            [
                ("称重台位移1", "车轮位移1"),
                ("称重台位移2", "车轮位移2"),
                ("称重台位移3", "车轮位移3"),
                ("称重台位移4", "车轮位移4"),
            ],
            [
                ("内测距激光1", "车轮内测距1"),
                ("内测距激光2", "车轮内测距2"),
                ("内测距激光3", "车轮内测距3"),
                ("内测距激光4", "车轮内测距4"),
            ],
            [
                ("轮高激光1", "轮高1"),
                ("轮高激光2", "轮高2"),
                ("轮高激光3", "轮高3"),
                ("轮高激光4", "轮高4"),
            ],
        ],
    ]

    # 需要后处理的点位及其在 bed.json「原点位置」中的基准键: 显示值 = 原始值 - 基准值
    # 例: "称重台X位移1" 减 bed.json["原点位置"]["滑台位移1"], ...
    _RELATIVE_POS_OFFSETS: dict[str, str] = {
        "称重台X位移1": "滑台位移1",
        "称重台X位移2": "滑台位移2",
        "称重台X位移3": "滑台位移3",
        "称重台X位移4": "滑台位移4",
        "车轮内侧距1": "滑台内测距1",
        "车轮内侧距2": "滑台内测距2",
        "车轮内侧距3": "滑台内测距3",
        "车轮内侧距4": "滑台内测距4",
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
                    led = PtLed(pt_name, parent=self, title=title)
                    if pt_name in self._RELATIVE_POS_OFFSETS:
                        led.afterUpdate.connect(self._show_relative_pos)
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


        # 紧急停止按钮
        self._emergency_btn = QPushButton("紧急停止", self)
        self._emergency_btn.setFixedSize(90, 36)
        self._emergency_btn.setCursor(Qt.PointingHandCursor)
        self._emergency_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #dc2626, stop:1 #b91c1c);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ef4444, stop:1 #dc2626);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #b91c1c, stop:1 #991b1b);
            }
        """)
        self._emergency_btn.clicked.connect(self._on_emergency_stop)
        layout.addWidget(self._emergency_btn, 0, Qt.AlignVCenter)

    @Slot(str)
    def _show_relative_pos(self, text: str) -> None:
        """PtLed 后处理: 显示值 = 原始值 - 原点位置基准值; 非数值(ON/OFF/ERR)不处理, 走默认显示.

        原点位置只与试验台有关, 取自 bed.json, 与当前车型/workflow 无关。
        当相对位移超出 [-limit, limit] 时, 控件背景置红(超限告警);
        未超限或 limit=None 时, 不改变背景颜色.
        """
        led = self.sender()
        if led is None:
            return
        base_key = self._RELATIVE_POS_OFFSETS.get(led._pt_name)
        if base_key is None:
            return

        # 从 bed.json 读取原点位置基准值
        base_pos = bed_section("原点位置")
        try:
            offset = float(base_pos[base_key])
        except (KeyError, TypeError, ValueError):
            return

        try:
            value = float(text.split()[0])
        except (IndexError, ValueError):
            return

        relative = value - offset
        led.set_display(f"{relative:.1f} mm")

        # 超限检测: 相对位移超出 [-limit, limit] 时背景置红
        if not (-LIMIT <= relative <= LIMIT):
            led.set_bg_color("#ff0000")

    def refresh_data(self) -> None:
        """刷新所有点位显示（由 plc_poll 信号触发，在主线程执行）"""
        for button in self._pt_buttons:
            button.update()
        for led in self._leds:
            led.update()

    def _on_emergency_stop(self) -> None:
        """紧急停止按钮点击处理"""
        plc = get_runtime().get("plc")
        if plc is None:
            return

        # 确认对话框
        reply = QMessageBox.question(
            self,
            "确认紧急停止",
            "确定要执行紧急停止吗？\n这将向 PLC 写入停止信号。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                plc._emc_stop()
            except Exception as e:
                logger.error(f"紧急停止失败: {e}")
                QMessageBox.warning(self, "失败", f"软急停失败: {e}")


def _format_duration(start_time: str | None, end_time: str | None) -> str:
    if not start_time or not end_time:
        return "-"
    try:
        started = datetime.strptime(start_time, "%y-%m-%d %H:%M:%S")
        ended = datetime.strptime(end_time, "%y-%m-%d %H:%M:%S")
    except ValueError:
        return "-"
    return f"{int((ended - started).total_seconds())}s"


def _format_result(result: object) -> str:
    if result is None:
        return "-"
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False)
    except TypeError:
        return str(result)


def _format_json_payload(payload: object) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except TypeError:
        return str(payload)


def _resolve_wait_seconds(node_args: object, trial_params: dict | None = None) -> float:
    if not isinstance(node_args, dict):
        return 0.0
    if str(node_args.get("algo") or "").strip().lower() != "wait":
        return 0.0
    data = node_args.get("data")
    if isinstance(data, dict):
        raw_seconds = data.get("seconds", data.get("delay", 0))
    elif data is None:
        raw_seconds = 0
    else:
        raw_seconds = data
    try:
        return max(0.0, float(raw_seconds))
    except (TypeError, ValueError):
        if isinstance(raw_seconds, str) and isinstance(trial_params, dict):
            key = raw_seconds.strip()
            if key in trial_params:
                try:
                    return max(0.0, float(trial_params[key]))
                except (TypeError, ValueError):
                    pass
        return 0.0


class WaitCountdownDialog(QDialog):
    wait_event = Signal(dict)

    def __init__(self, total_seconds: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = get_runtime()
        self._total_seconds = max(0, math.ceil(total_seconds))
        self._remaining_seconds = self._total_seconds
        self._broker_subscriptions: list[object] = []
        self.setWindowTitle("等待中")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        self.resize(360, 240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        self._countdown_label = QLabel(self)
        self._countdown_label.setAlignment(Qt.AlignCenter)
        self._countdown_label.setStyleSheet("color: #f28c28; font-size: 72px; font-weight: 800;")
        layout.addStretch(1)
        layout.addWidget(self._countdown_label)

        self._cancel_button = QPushButton("跳过等待", self)
        self._cancel_button.setMinimumHeight(44)
        layout.addWidget(self._cancel_button)
        layout.addStretch(1)

        self.wait_event.connect(self._apply_wait_payload)
        self._render_countdown()
        self._subscribe()

    def set_skip_handler(self, handler) -> None:
        self._cancel_button.clicked.connect(handler)

    def _render_countdown(self) -> None:
        self._countdown_label.setText(str(max(0, self._remaining_seconds)))

    def _subscribe(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            return
        self._broker_subscriptions = [broker.subscribe("node_wait", self._on_node_wait)]

    def _unsubscribe(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            self._broker_subscriptions.clear()
            return
        for subscription in self._broker_subscriptions:
            broker.unsubscribe(subscription)
        self._broker_subscriptions.clear()

    def _on_node_wait(self, **payload) -> None:
        self.wait_event.emit(dict(payload))

    def _apply_wait_payload(self, payload: dict[str, object]) -> None:
        total = payload.get("total")
        remaining = payload.get("remaining")
        try:
            if total is not None:
                self._total_seconds = max(0, math.ceil(float(total)))
            if remaining is not None:
                self._remaining_seconds = max(0, math.ceil(float(remaining)))
        except (TypeError, ValueError):
            return
        self._render_countdown()
        if self._remaining_seconds <= 0:
            self._unsubscribe()
            self.accept()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._unsubscribe()
        super().closeEvent(event)

class WorkflowRunner(QThread):
    node_begin_event = Signal(dict)
    node_event = Signal(dict)
    data_event = Signal(object)
    state_event = Signal(str, str)
    select_request = Signal(str, str, object)
    loop_request = Signal(str, str)
    confirm_request = Signal(str, str, str, object)
    result_request = Signal(list)

    def __init__(self, workflow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workflow = workflow
        self._stopping = False
        self._select_event = Event()
        self._loop_event = Event()
        self._confirm_event = Event()
        self._result_event = Event()
        self._selected_node_id: str | None = None
        self._loop_count: int | None = None
        self._confirm_result = False
        self._result_data: list = []
        self._result_result: bool = False
        self._pending_select_payload: tuple[str, str, list[dict]] | None = None
        self._select_reopen_requested: bool = False

    def stop(self) -> None:
        self._stopping = True
        self._select_event.set()
        self._loop_event.set()
        self._confirm_event.set()
        self._result_event.set()
        runtime = get_runtime()
        plc = runtime.get("plc")
        cancel_pending_actions = getattr(plc, "cancel_pending_actions", None)
        if callable(cancel_pending_actions):
            cancel_pending_actions()
        if self._workflow is not None:
            self._workflow.stop()

    def skip_wait(self) -> None:
        if self._workflow is not None:
            self._workflow.skip_wait()

    def submit_selection(self, selected_node_id: str | None) -> None:
        self._selected_node_id = selected_node_id
        self._select_event.set()

    def reopen_select(self) -> None:
        if self._pending_select_payload is not None and not self._stopping:
            self._select_reopen_requested = True
            self._select_event.set()

    def submit_loop_count(self, loop_count: int | None) -> None:
        self._loop_count = loop_count
        self._loop_event.set()

    def submit_confirmation(self, confirmed: bool) -> None:
        self._confirm_result = confirmed
        self._confirm_event.set()

    def run(self) -> None:
        runtime = get_runtime()
        workflow = self._workflow
        if workflow is None:
            self.state_event.emit("error", "workflow instance is missing")
            return
        if hasattr(workflow.events, "_handlers"):
            workflow.events._handlers.clear()

        workflow.events.on("evt_node_begin", self._on_node_begin)
        workflow.events.on("evt_node_done", self._on_node_done)
        workflow.events.on("evt_node_error", self._on_node_error)
        workflow.events.on("evt_wf_start", self._on_workflow_start)
        workflow.events.on("evt_wf_done", lambda workflow: self._emit_data(workflow))
        workflow.events.on("evt_wf_stop", lambda workflow: self._emit_data(workflow))
        workflow.events.on("evt_wf_error", lambda workflow, error=None: self._emit_data(workflow))

        workflow.select_handler = self._select_handler
        workflow.loop_handler = self._loop_handler
        workflow.confirm_handler = self._confirm_handler
        workflow.result_handler = self._result_handler
        workflow.broker = runtime["broker"]


        try:
            runtime["wf"] = workflow
            state = asyncio.run(workflow.start())
            self.state_event.emit(state.value, "")
        except Exception as exc:
            self.state_event.emit("error", str(exc))
        finally:
            self._emit_data(workflow)

    def _on_workflow_start(self, workflow) -> None:
        # business_data = copy.deepcopy(getattr(workflow, "_business_data", {}))
        # workflow.data["基础数据"] = business_data
        self._emit_data(workflow)

    def _emit_data(self, workflow) -> None:
        self.data_event.emit(copy.deepcopy(workflow.data))

    def _on_node_begin(self, workflow, node) -> None:
        del workflow
        self.node_begin_event.emit(
            {
                "node_id": node.node_id,
                "node_name": node.node_name,
                "node_type": node.node_type,
                "node_args": copy.deepcopy(node.args),
            }
        )

    def _on_node_done(self, workflow, node, result=None) -> None:
        self.node_event.emit(
            {
                "node_name": node.node_name,
                "state": node.state.value,
                "runtime": _format_duration(node.stime, node.etime),
                "args": copy.deepcopy(node.args),
                "node_log": copy.deepcopy(node.node_logs),
                "desc": node.desc
            }
        )
        self._emit_data(workflow)

    def _on_node_error(self, workflow, node, error=None) -> None:
        del error
        self.node_event.emit(
            {
                "node_name": node.node_name,
                "state": node.state.value,
                "runtime": _format_duration(node.stime, node.etime),
                "args": copy.deepcopy(node.args),
                "node_log": copy.deepcopy(node.node_logs),
                "desc": node.desc
            }
        )
        self._emit_data(workflow)

    def _select_handler(self, node, choices: list[str]) -> str:
        if not choices:
            raise RuntimeError(f"select node {node.node_id} has no choices")
        choice_items = []
        for choice_id in choices:
            if self._workflow is None:
                choice_name = choice_id
                choice_state = WorkflowState.IDLE.value
            else:
                choice_node = self._workflow.nodes[choice_id]
                choice_name = choice_node.node_name
                choice_state = choice_node.state.value
            choice_items.append({
                "id": choice_id,
                "name": choice_name,
                "state": choice_state,
            })
        choice_items.sort(key=lambda item: item["name"])
        self._pending_select_payload = (node.node_id, node.node_name, choice_items)
        self._select_event.clear()
        self._selected_node_id = None
        self._select_reopen_requested = False
        self.select_request.emit(node.node_id, node.node_name, choice_items)
        while True:
            triggered = self._select_event.wait(0.05)
            if self._stopping:
                self._pending_select_payload = None
                raise NodeStoppedError("workflow stopped")
            if triggered:
                self._select_event.clear()
                if self._select_reopen_requested:
                    self._select_reopen_requested = False
                    if self._pending_select_payload is not None:
                        nid, nname, citems = self._pending_select_payload
                        self.select_request.emit(nid, nname, citems)
                    continue
                break
        self._pending_select_payload = None
        if self._selected_node_id not in choices:
            raise RuntimeError(f"invalid selection for node {node.node_id}")
        return self._selected_node_id

    def _loop_handler(self, node) -> int:
        self._loop_event.clear()
        self._loop_count = None
        self.loop_request.emit(node.node_id, node.node_name)
        while not self._loop_event.wait(0.05):
            if self._stopping:
                raise NodeStoppedError("workflow stopped")
        if self._stopping:
            raise NodeStoppedError("workflow stopped")
        if self._loop_count is None or self._loop_count < 1:
            raise NodeStoppedError("workflow stopped")
        return self._loop_count

    def _confirm_handler(self, node) -> bool:
        self._confirm_event.clear()
        self._confirm_result = False
        self.confirm_request.emit(node.node_id, node.node_name, node.node_type, copy.deepcopy(node.args))
        while not self._confirm_event.wait(0.05):
            if self._stopping:
                raise NodeStoppedError("workflow stopped")
        if self._stopping:
            raise NodeStoppedError("workflow stopped")
        return self._confirm_result

    def _result_handler(self, node, result_data: list) -> bool:
        """处理显示结果对话框的请求"""
        self._result_event.clear()
        self._result_data = result_data
        self._result_result = False
        self.result_request.emit(result_data)
        while not self._result_event.wait(0.05):
            if self._stopping:
                raise NodeStoppedError("workflow stopped")
        if self._stopping:
            raise NodeStoppedError("workflow stopped")
        return self._result_result

    def submit_result(self, result: bool) -> None:
        """提交结果对话框的响应"""
        self._result_result = result
        self._result_event.set()

class _EnterKeyBlocker(QObject):
    """事件过滤器: 吞掉回车键, 禁止其在目标控件上触发任何动作.

    仅拦截 KeyPress 的 Return / Enter (小键盘), 其余按键原样放行.
    返回 True 表示事件已被处理, Qt 不会再把它传给目标控件, 也不会走
    "默认按钮被回车激活" 那条路径.
    """

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                return True
        return super().eventFilter(watched, event)


class SelectBranchDialog(QDialog):
    """分支选择对话框: ListWidget 大字体显示, 只展示节点名称."""

    # 分支节点状态 -> ListWidgetItem 背景色映射
    # 未列出 (待执行 / 执行中 / 停止) 走默认白底
    _STATE_BG: dict[str, str] = {
        WorkflowState.DONE.value: "#fef3c7",   # 淡黄 (已完成)
        WorkflowState.ERROR.value: "#fee2e2",  # 淡红 (错误)
    }

    def __init__(self, node_name: str, choices: list[dict[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择试验流程")
        self.setMinimumSize(500, 600)
        self.resize(500, 600)

        self._selected_id: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        # title = QLabel(node_name, self)
        # title.setObjectName("selectDialogTitle")
        # root.addWidget(title)

        prompt = QLabel("请选择后续试验流程", self)
        prompt.setObjectName("selectDialogPrompt")
        root.addWidget(prompt)

        from PySide6.QtGui import QBrush, QColor  # 本地导入, 仅此处使用

        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("selectDialogList")
        self.list_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for item in choices:
            lw_item = QListWidgetItem(item["name"])
            lw_item.setData(Qt.ItemDataRole.UserRole, item["id"])
            # 按分支节点状态着色 (DONE 黄色 / ERROR 红色, 其他默认)
            bg_hex = self._STATE_BG.get(item.get("state") or "")
            if bg_hex:
                lw_item.setBackground(QBrush(QColor(bg_hex)))
            self.list_widget.addItem(lw_item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._accept_current())
        root.addWidget(self.list_widget, 1)

        custom_frame = QFrame(self)
        custom_frame.setObjectName("customPressFrame")
        custom_layout = QHBoxLayout(custom_frame)
        custom_layout.setContentsMargins(0, 8, 0, 0)
        custom_layout.setSpacing(8)

        custom_label = QLabel("设定压力(kN):", custom_frame)
        self._pressure_edit = QLineEdit(custom_frame)
        self._pressure_edit.setPlaceholderText("0-120")
        self._pressure_edit.setMaximumWidth(80)
        self._pressure_edit.setAlignment(Qt.AlignCenter)

        press_btn = QPushButton("自定义加载", custom_frame)
        press_btn.setObjectName("customPressBtn")
        press_btn.setStyleSheet("background: #dc2626; color: white; border: none; border-radius: 6px; padding: 8px 16px; font-weight: bold;")
        press_btn.clicked.connect(self._on_custom_press)

        custom_layout.addWidget(custom_label)
        custom_layout.addWidget(self._pressure_edit)
        custom_layout.addWidget(press_btn)
        custom_layout.addStretch(1)
        root.addWidget(custom_frame)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok_btn = QPushButton("确认", self)
        ok_btn.setObjectName("selectDialogBtnPrimary")
        # 防止误触回车直接确认:
        # 1) setDefault(False): 不作为对话框默认按钮, 回车不再激活它
        # 2) setAutoDefault(False): QPushButton 放在 QDialog 中 autoDefault 默认为 true,
        #    一旦按钮获得焦点就会被"提升"为默认按钮, 回车同样会触发; 这里显式关闭
        # 确认途径保留: 鼠标点击 / 双击列表项 / Tab 到按钮后按空格
        ok_btn.setDefault(False)
        ok_btn.setAutoDefault(False)
        ok_btn.clicked.connect(self._accept_current)
        buttons.addWidget(ok_btn)
        root.addLayout(buttons)

        # 初始焦点交给列表, 回车不会触发任何确认动作 (方向键仍可切换选项)
        self.list_widget.setFocus()

        # 全局禁用回车: 在本对话框及其所有子控件上装过滤器,
        # 回车/小键盘回车一律吞掉, 不会确认、不会触发"自定义加载"写入 PLC
        self._enter_blocker = _EnterKeyBlocker(self)
        self.installEventFilter(self._enter_blocker)
        for child in self.findChildren(QWidget):
            child.installEventFilter(self._enter_blocker)

        self.setStyleSheet(
            "QDialog { background-color: #f8fafc; }"
            "QLabel#selectDialogTitle {"
            " font-size: 26px; font-weight: 500; color: #1e293b; background: none;"
            "}"
            "QLabel#selectDialogPrompt {"
            " font-size: 15px; font-weight: 500; color: #b45309; background: #fef3c7;"
            " border: 1px solid #f59e0b; border-radius: 6px; padding: 8px 12px;"
            "}"
            "QListWidget#selectDialogList {"
            " font-size: 15px; font-weight: 500; color: #0f172a;"
            " background: #ffffff; border: 2px solid #cbd5e1; border-radius: 6px;"
            " padding: 6px;"
            "}"
            "QListWidget#selectDialogList::item {"
            " border-radius: 4px;"
            "}"
            "QListWidget#selectDialogList::item:selected {"
            " background: #2563eb; color: #ffffff;"
            "}"
            "QListWidget#selectDialogList::item:hover {"
            " background: #e0e7ff;"
            "}"
            "QPushButton {"
            " font-size: 15px; font-weight: 300; padding: 10px 28px;"
            " border-radius: 6px;"
            "}"
            "QPushButton#selectDialogBtn {"
            " background: #e2e8f0; color: #334155; border: 1px solid #94a3b8;"
            "}"
            "QPushButton#selectDialogBtnPrimary {"
            " background: #2563eb; color: #ffffff; border: 1px solid #1d4ed8;"
            "}"
            "QPushButton#selectDialogBtnPrimary:hover { background: #1d4ed8; }"
        )

    def _accept_current(self) -> None:
        current = self.list_widget.currentItem()
        if current is None:
            return
        self._selected_id = current.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def selected_id(self) -> str | None:
        return self._selected_id

    def _on_custom_press(self) -> None:
        raw = self._pressure_edit.text().strip()
        if not raw.isdigit():
            QMessageBox.warning(self, "输入错误", "压力值必须是整数")
            return
        val = int(raw)
        if val < 0 or val > 120:
            QMessageBox.warning(self, "输入错误", "压力值必须在 0-120 之间")
            return

        reply = QMessageBox.question(
            self,
            "确认加载",
            f"自定义加载目标压力为{val}kN, 是否加载?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._custom_press(val)

    def _custom_press(self, target_kn: int) -> None:
        plc = get_runtime().get("plc")
        if plc is None:
            QMessageBox.warning(self, "PLC未连接", "PLC未初始化")
            return

        try:
            plc.write("设定加载头1加载力", target_kn)
            plc.write("设定加载头2加载力", target_kn)
        except Exception as e:
            QMessageBox.warning(self, "写入失败", f"写入目标压力失败: {e}")
            return

        try:
            p1 = float(plc.read("加载压力1"))
            p2 = float(plc.read("加载压力2"))
            max_p = max(p1, p2)
            min_p = min(p1, p2)
        except Exception as e:
            QMessageBox.warning(self, "读取失败", f"读取当前压力失败: {e}")
            return

        if target_kn > max_p:
            try:
                plc.write("力工进", True)
                QTimer.singleShot(1000, lambda: self._reset_point("力工进"))
            except Exception as e:
                QMessageBox.warning(self, "PLC操作失败", f"力工进操作失败: {e}")
        elif target_kn < min_p:
            try:
                plc.write("力工退", True)
                QTimer.singleShot(1000, lambda: self._reset_point("力工退"))
            except Exception as e:
                QMessageBox.warning(self, "PLC操作失败", f"力工退操作失败: {e}")

    def _reset_point(self, pt_name: str) -> None:
        plc = get_runtime().get("plc")
        if plc is None:
            return
        try:
            plc.write(pt_name, False)
        except Exception:
            pass

class WorkflowRuntimePanel(QWidget):
    state_changed = Signal(str, str)
    running_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None, *, show_title: bool = True, show_controls: bool = True, show_data: bool = True, flow_graph=None) -> None:
        super().__init__(parent)
        self.runtime = get_runtime()
        self.workflow = None
        self.runner: WorkflowRunner | None = None
        self._wait_dialog: WaitCountdownDialog | None = None
        self._select_dialog: SelectBranchDialog | None = None
        self._loop_dialog: QInputDialog | None = None
        self._confirm_dialog: ConfirmDialog | None = None
        self._result_dialog: ResultDialog | None = None
        self.show_data = show_data
        self._flow_graph = flow_graph
        self._data_panel_expanded = True
        self._node_rows: list[dict[str, object]] = []
        self._workflow_data: dict[str, object] | None = None
        self._state = "idle"
        self._error_message = ""
        self._build_ui(show_title=show_title, show_controls=show_controls)
        self._refresh_initial_data()

    def _build_ui(self, *, show_title: bool, show_controls: bool) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        if show_title:
            header = QLabel("试验流程测试", self)
            header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            header.setStyleSheet("font-size: 18px; font-weight: 600; margin: 1px 0;")
            root.addWidget(header)
        if show_controls:
            controls = QHBoxLayout()
            controls.setSpacing(2)
            self.start_btn = QPushButton("开始", self)
            self.stop_btn = QPushButton("停止", self)
            self.start_btn.clicked.connect(self.start_workflow)
            self.stop_btn.clicked.connect(self.stop_workflow)
            controls.addWidget(self.start_btn)
            controls.addWidget(self.stop_btn)
            controls.addStretch(1)
            root.addLayout(controls)
        else:
            self.start_btn = None
            self.stop_btn = None
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(4)
        self.state_label = QLabel("状态: idle", self)
        status_row.addWidget(self.state_label)
        status_row.addStretch(1)
        if self.show_data:
            self.data_toggle_btn = QToolButton(self)
            self.data_toggle_btn.setText("展开数据")
            self.data_toggle_btn.clicked.connect(self._toggle_data_panel)
            status_row.addWidget(self.data_toggle_btn)
        else:
            self.data_toggle_btn = None
        root.addLayout(status_row)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(6)
        self.node_table = QTableWidget(0, 4, self)
        self.node_table.setHorizontalHeaderLabels(["节点名称", "状态", "运行时间", "节点描述"])
        self.node_table.horizontalHeader().setStretchLastSection(True)
        self.node_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.node_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.content_splitter.addWidget(self.node_table)
        if self.show_data:
            self.data_panel = QFrame(self)
            self.data_panel.setObjectName("workflowDataPanel")
            data_layout = QVBoxLayout(self.data_panel)
            data_layout.setContentsMargins(6, 6, 6, 6)
            data_layout.setSpacing(4)
            data_title = QLabel("试验流程数据内容", self.data_panel)
            data_layout.addWidget(data_title)
            self.data_tree = QTreeWidget(self.data_panel)
            self.data_tree.setHeaderLabels(["字段", "数值", "类型"])
            self.data_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.data_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.data_tree.setAlternatingRowColors(True)
            self.data_tree.setRootIsDecorated(True)
            self.data_tree.setWordWrap(False)
            self.data_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.data_tree.header().setStretchLastSection(False)
            data_layout.addWidget(self.data_tree, 1)
            self.content_splitter.addWidget(self.data_panel)
            self.content_splitter.setStretchFactor(0, 2)
            self.content_splitter.setStretchFactor(1, 1)
            # 不使用固定尺寸，让 splitter 自适应
        else:
            self.data_panel = None
            self.data_tree = None
        content_row.addWidget(self.content_splitter, 1)
        root.addLayout(content_row, 1)
        self._set_data_panel_visible(True)
        self._set_running_ui(False)

    def _toggle_data_panel(self) -> None:
        self._set_data_panel_visible(not self._data_panel_expanded)

    def _set_data_panel_visible(self, visible: bool) -> None:
        self._data_panel_expanded = bool(visible) and self.show_data and self.data_panel is not None
        if self.data_panel is not None:
            self.data_panel.setVisible(self._data_panel_expanded)
        if self.data_toggle_btn is not None:
            self.data_toggle_btn.setText("隐藏数据详情" if self._data_panel_expanded else "查看数据详情")

    def set_workflow_instance(self, workflow = None) -> None:
        self.workflow = workflow
        if not self.is_running():
            self._restore_workflow_runtime()

    def is_running(self) -> bool:
        return self.runner is not None and self.runner.isRunning()

    def start_workflow(self) -> None:
        if self.is_running():
            return
        if self.workflow is None:
            self._state = "error"
            self._error_message = "当前未创建试验流程。"
            self.state_label.setText("状态: no-template")
            self.state_changed.emit("error", self._error_message)
            self._persist_runtime_state()
            return
        self._node_rows = []
        self._error_message = ""
        self._state = "running"
        self._workflow_data = copy.deepcopy(self.workflow.data)
        self.node_table.setRowCount(0)
        # 重新预填充节点表格，重置状态为"待运行"
        self._node_rows_extend(self.workflow.get_node_list())
        self.state_label.setText("状态: running")
        self._render_data_text()
        self._set_running_ui(True)
        logger.info(f"流程开始: Name={self.workflow.name}")
        self._persist_runtime_state()
        self.runner = WorkflowRunner(self.workflow, parent=self)
        self.runner.node_begin_event.connect(self._handle_node_begin)
        self.runner.node_event.connect(self._append_node_row)
        self.runner.data_event.connect(self._handle_data_event)
        self.runner.state_event.connect(self._handle_state)
        self.runner.select_request.connect(self._request_selection)
        self.runner.loop_request.connect(self._request_loop_count)
        self.runner.confirm_request.connect(self._request_confirmation)
        self.runner.result_request.connect(self._show_result_dialog)
        self.runner.finished.connect(self._on_runner_finished)
        self.runner.start()
        self._persist_runtime_state()

    def stop_workflow(self) -> None:
        if self.runner is None:
            return
        logger.info(f"试验流程中止")
        self.state_label.setText("状态: stopping")
        self.runner.stop()

    def shutdown(self, timeout_ms: int = 3000) -> None:
        self._close_wait_dialog()
        self._close_select_dialog()
        self._close_loop_dialog()
        self._close_confirm_dialog()
        self._close_result_dialog()
        runner = self.runner
        if runner is None:
            return
        logger.info(f"试验流程线程关闭")
        runner.stop()
        if not runner.wait(timeout_ms):
            logger.warning(f"试验流程线程未在 %sms 内退出", timeout_ms)
            runner.terminate()
            runner.wait(1000)
        self.runner = None
        self._set_running_ui(False)

    def _refresh_initial_data(self) -> None:
        self._restore_workflow_runtime()

    def _set_running_ui(self, running: bool) -> None:
        if self.start_btn is not None:
            self.start_btn.setEnabled(not running)
        if self.stop_btn is not None:
            self.stop_btn.setEnabled(running)
        self.running_changed.emit(running)

    def _append_node_row(self, payload: dict) -> None:
        """
        添加或更新节点行
        如果预填充的表中已有该节点，则更新；否则追加新行
        """
        node_name = payload.get("node_name", "")
        # 查找是否已存在该节点的行
        existing_row_index = -1
        for i, row_data in enumerate(self._node_rows):
            if row_data.get("node_name") == node_name:
                existing_row_index = i
                break

        if existing_row_index >= 0:
            # 更新已存在的行
            self._node_rows[existing_row_index] = copy.deepcopy(payload)
            self._update_node_row(existing_row_index, payload)
        else:
            # 追加新行
            self._node_rows.append(copy.deepcopy(payload))
            self._insert_node_row(payload)
        self.node_table.scrollToBottom()
        self._persist_runtime_state()
        self._update_flow_graph()

    def _update_node_row(self, row_index: int, payload: dict) -> None:
        """更新指定行的内容"""
        tooltip = self._node_row_tooltip(payload)
        values = [
            str(payload.get("node_name", "")),
            str(payload.get("state", "")),
            str(payload.get("runtime", "")),
            str(payload.get("desc", "")),
        ]
        for column, value in enumerate(values):
            item = self.node_table.item(row_index, column)
            if item:
                item.setText(value)
                item.setToolTip(tooltip)
        # 根据状态设置行颜色
        self._apply_row_state_color(row_index, payload.get("state", ""))

    def _node_rows_extend(self, node_list: list[dict]) -> None:
        """
        批量添加节点行（用于预填充待运行的节点）

        Args:
            node_list: 节点列表
        """
        for node_info in node_list:
            payload = self._make_pending_node_payload(node_info)
            self._node_rows.append(payload)
            self._insert_node_row(payload)

    def _make_pending_node_payload(self, node_info: dict) -> dict:
        """
        创建待运行状态的节点数据

        Args:
            node_info: 节点信息，包含 node_id, node_name, node_type

        Returns:
            节点 payload 数据
        """
        return {
            "node_id": node_info.get("node_id", ""),
            "node_name": node_info.get("node_name", ""),
            "node_type": node_info.get("node_type", ""),
            "desc": node_info.get("desc", ""),
            "state": "待运行",
            "runtime": "",
            "args": {},
            "node_log": [],
        }

    def _handle_data_event(self, workflow_data: object) -> None:
        self._workflow_data = copy.deepcopy(workflow_data) if isinstance(workflow_data, dict) else None
        self._render_data_text()
        self._persist_runtime_state()

    def _handle_node_begin(self, payload: dict[str, object]) -> None:
        node_type = str(payload.get("node_type") or "").strip()
        node_args = payload.get("node_args")
        node_name = str(payload.get("node_name", ""))
        current_desc = ""
        for row_data in self._node_rows:
            if row_data.get("node_name") == node_name:
                current_desc = str(row_data.get("desc", ""))
                break
        self._append_node_row(
            {
                "node_name": node_name,
                "state": WorkflowState.RUNNING.value,
                "runtime": "",
                "args": copy.deepcopy(node_args) if isinstance(node_args, dict) else {},
                "node_log": [],
                "desc": current_desc,
            }
        )
        trial_params = (
            self._workflow_data.get("试验参数", {})
            if isinstance(self._workflow_data, dict)
            else {}
        )
        wait_seconds = _resolve_wait_seconds(node_args, trial_params)
        if node_type == "sys" and wait_seconds > 0:
            self._show_wait_dialog(wait_seconds)
            return
        self._close_wait_dialog()
        self._update_flow_graph()

    def _update_flow_graph(self) -> None:
        if self._flow_graph is not None and self.workflow is not None:
            self._flow_graph.update(self.workflow)

    def _request_selection(self, node_id: str, node_name: str, choices: list[dict[str, str]]) -> None:
        if self.runner is None:
            return
        del node_id
        self._close_select_dialog()
        dialog = SelectBranchDialog(node_name, choices, self)
        self._select_dialog = dialog
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)

        def handle_finished(result: int) -> None:
            if self._select_dialog is not dialog:
                dialog.deleteLater()
                return
            self._select_dialog = None
            runner = self.runner
            selected_id = dialog.selected_id() if result == QDialog.Accepted else None
            valid_selection = selected_id is not None and any(item["id"] == selected_id for item in choices)
            if runner is not None and valid_selection:
                runner.submit_selection(selected_id)
            dialog.deleteLater()

        dialog.finished.connect(handle_finished)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _request_loop_count(self, node_id: str, node_name: str) -> None:
        if self.runner is None:
            return
        self._close_loop_dialog()
        dialog = QInputDialog(self)
        self._loop_dialog = dialog
        dialog.setWindowTitle("输入循环次数")
        dialog.setLabelText(f"{node_name} ({node_id})\n请输入循环次数")
        dialog.setInputMode(QInputDialog.InputMode.IntInput)
        dialog.setIntRange(1, 9999)
        dialog.setIntStep(1)
        dialog.setIntValue(1)
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)

        def handle_finished(result: int) -> None:
            if self._loop_dialog is not dialog:
                dialog.deleteLater()
                return
            self._loop_dialog = None
            runner = self.runner
            accepted = result == QDialog.Accepted
            if runner is not None:
                if not accepted:
                    runner.stop()
                    runner.submit_loop_count(None)
                else:
                    runner.submit_loop_count(int(dialog.intValue()))
            dialog.deleteLater()

        dialog.finished.connect(handle_finished)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _close_select_dialog(self) -> None:
        if self._select_dialog is None:
            return
        dialog = self._select_dialog
        self._select_dialog = None
        try:
            dialog.finished.disconnect()
        except (TypeError, RuntimeError):
            pass
        dialog.close()
        dialog.deleteLater()

    def _close_loop_dialog(self) -> None:
        if self._loop_dialog is None:
            return
        dialog = self._loop_dialog
        self._loop_dialog = None
        try:
            dialog.finished.disconnect()
        except (TypeError, RuntimeError):
            pass
        dialog.close()
        dialog.deleteLater()

    def _close_wait_dialog(self) -> None:
        if self._wait_dialog is None:
            return
        dialog = self._wait_dialog
        self._wait_dialog = None
        dialog._unsubscribe()
        dialog.close()
        dialog.deleteLater()

    def _skip_wait_dialog(self) -> None:
        if self.runner is not None:
            self.runner.skip_wait()
        self._close_wait_dialog()

    def _show_wait_dialog(self, wait_seconds: float) -> None:
        self._close_wait_dialog()
        self._wait_dialog = WaitCountdownDialog(wait_seconds, self)
        self._wait_dialog.set_skip_handler(self._skip_wait_dialog)
        self._wait_dialog.finished.connect(self._handle_wait_dialog_finished)
        self._wait_dialog.show()
        self._wait_dialog.raise_()
        self._wait_dialog.activateWindow()

    def _handle_wait_dialog_finished(self, _result: int) -> None:
        if self._wait_dialog is None:
            return
        dialog = self._wait_dialog
        self._wait_dialog = None
        dialog.deleteLater()

    def _close_confirm_dialog(self) -> None:
        if self._confirm_dialog is None:
            return
        dialog = self._confirm_dialog
        self._confirm_dialog = None
        try:
            dialog.finished.disconnect()
        except (TypeError, RuntimeError):
            pass
        dialog.close()
        dialog.deleteLater()

    def _request_confirmation(self, node_id: str, node_name: str, node_type: str, node_args: object) -> None:
        if self.runner is None:
            return
        del node_id, node_type
        # 从 node_args 中提取附加信息
        info = ""
        if isinstance(node_args, dict):
            info = str(node_args.get("info", "")).strip()

        self._close_confirm_dialog()
        dialog = ConfirmDialog(node_name, info, self)
        self._confirm_dialog = dialog

        def handle_finished(result: int) -> None:
            if self._confirm_dialog is not dialog:
                dialog.deleteLater()
                return
            self._confirm_dialog = None
            runner = self.runner
            if runner is None:
                dialog.deleteLater()
                return
            confirmed = result == QDialog.Accepted
            if not confirmed:
                runner.stop()
            runner.submit_confirmation(confirmed)
            dialog.deleteLater()

        dialog.finished.connect(handle_finished)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _show_result_dialog(self, result_data: list) -> None:
        """显示试验结果对话框并等待用户确认"""
        if self.runner is None:
            return
        self._close_result_dialog()
        dialog = ResultDialog(result_data, self)
        self._result_dialog = dialog
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)

        def handle_finished(result: int) -> None:
            if self._result_dialog is not dialog:
                dialog.deleteLater()
                return
            self._result_dialog = None
            runner = self.runner
            confirmed = result == QDialog.Accepted
            if runner is not None:
                if not confirmed:
                    runner.stop()
                runner.submit_result(confirmed)
            dialog.deleteLater()

        dialog.finished.connect(handle_finished)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _close_result_dialog(self) -> None:
        if self._result_dialog is None:
            return
        dialog = self._result_dialog
        self._result_dialog = None
        try:
            dialog.finished.disconnect()
        except (TypeError, RuntimeError):
            pass
        dialog.close()
        dialog.deleteLater()

    def _handle_state(self, state: str, error_message: str) -> None:
        self._state = state
        self._error_message = error_message
        self.state_label.setText(f"状态: {state}")
        self.state_changed.emit(state, error_message)
        if error_message:
            logger.error(f"workflow execution failed: %s", error_message)
            QMessageBox.warning(self, "试验流程执行失败", error_message)
        else:
            logger.info(f"流程结束")
        self._persist_runtime_state()

    def _on_runner_finished(self) -> None:
        self._close_wait_dialog()
        self._close_select_dialog()
        self._close_loop_dialog()
        self._close_confirm_dialog()
        self._close_result_dialog()
        self._set_running_ui(False)
        self.runner = None
        self._persist_runtime_state()

    def _restore_workflow_runtime(self) -> None:
        if self.workflow is None:
            self._node_rows = []
            self._workflow_data = None
            self._state = "idle"
            self._error_message = ""
        else:
            self._node_rows = copy.deepcopy(getattr(self.workflow, "_ui_node_rows", []))
            self._workflow_data = copy.deepcopy(self.workflow.data)
            self._state = str(getattr(self.workflow, "_ui_state", self.workflow.state.value or "idle"))
            self._error_message = str(getattr(self.workflow, "_ui_error_message", ""))
        self._render_runtime()
        self._persist_runtime_state()

    def _render_runtime(self) -> None:
        state_text = self._state or ("idle" if self.workflow is not None else "no-template")
        if self.workflow is None:
            state_text = "no-template"
        self.state_label.setText(f"状态: {state_text}")
        self.node_table.setRowCount(0)
        for payload in self._node_rows:
            self._insert_node_row(payload)
        self._render_data_text()

    def _render_data_text(self) -> None:
        if self.data_tree is None:
            return
        self.data_tree.clear()
        if self._workflow_data is None:
            return
        if isinstance(self._workflow_data, dict):
            for key, value in self._workflow_data.items():
                self.data_tree.addTopLevelItem(self._build_data_tree_item(str(key), value))
        elif isinstance(self._workflow_data, list):
            for index, value in enumerate(self._workflow_data):
                self.data_tree.addTopLevelItem(self._build_data_tree_item(f"[{index}]", value))
        else:
            self.data_tree.addTopLevelItem(self._build_data_tree_item("value", self._workflow_data))
        self.data_tree.collapseAll()
        self.data_tree.resizeColumnToContents(0)
        self.data_tree.resizeColumnToContents(1)
        self.data_tree.resizeColumnToContents(2)

    def _insert_node_row(self, payload: dict) -> None:
        row_index = self.node_table.rowCount()
        self.node_table.insertRow(row_index)
        tooltip = self._node_row_tooltip(payload)
        values = [
            str(payload.get("node_name", "")),
            str(payload.get("state", "")),
            str(payload.get("runtime", "")),
            str(payload.get("desc", "")),
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setToolTip(tooltip)
            self.node_table.setItem(row_index, column, item)
        # 根据状态设置行颜色
        self._apply_row_state_color(row_index, payload.get("state", ""))

    def _apply_row_state_color(self, row_index: int, state: str) -> None:
        """根据节点状态设置行颜色"""
        from PySide6.QtGui import QColor, QBrush
        color_map = {
            WorkflowState.IDLE: QColor("#E8E8E8"),  # 浅灰
            WorkflowState.RUNNING: QColor("#BBF7D0"),  # 绿色
            WorkflowState.DONE: QColor("#E8F5E9"),  # 浅绿
            WorkflowState.ERROR: QColor("#FFEBEE"),  # 浅红
            WorkflowState.STOPPED: QColor("#FFF8E1"),  # 浅黄
        }
        bg_color = color_map.get(state)
        if bg_color:
            for col in range(self.node_table.columnCount()):
                item = self.node_table.item(row_index, col)
                if item:
                    item.setBackground(QBrush(bg_color))

    def _node_row_tooltip(self, payload: dict) -> str:
        tooltip_payload = {
            "args": payload.get("args", {}),
            "node_log": payload.get("node_log", []),
        }
        return _format_json_payload(tooltip_payload)

    def _build_data_tree_item(self, key: str, value: object) -> QTreeWidgetItem:
        if isinstance(value, dict):
            item = QTreeWidgetItem([key, "...", "dict"])
            for child_key, child_value in value.items():
                item.addChild(self._build_data_tree_item(str(child_key), child_value))
            return item
        if isinstance(value, list):
            item = QTreeWidgetItem([key, "...", "list"])
            for index, child_value in enumerate(value):
                item.addChild(self._build_data_tree_item(f"[{index}]", child_value))
            return item
        return QTreeWidgetItem([key, self._format_tree_scalar(value), self._tree_type_name(value)])

    def _format_tree_scalar(self, value: object) -> str:
        if isinstance(value, str):
            return value
        return _format_json_payload(value)

    def _tree_type_name(self, value: object) -> str:
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

    def _persist_runtime_state(self) -> None:
        if self.workflow is None:
            return
        self.workflow._ui_node_rows = copy.deepcopy(self._node_rows)
        self.workflow._ui_state = self._state
        self.workflow._ui_error_message = self._error_message

    def _prefill_node_table(self, node_list: list[dict]) -> None:
        """
        预填充节点表格，在运行前展示流程全貌

        Args:
            node_list: 节点列表，每个元素包含 node_id, node_name, node_type
        """
        self.node_table.setRowCount(0)
        self._node_rows.clear()
        self._node_rows_extend(node_list)

class Window(QWidget):
    _plc_poll = Signal()  # 跨线程信号：plc_poll → 主线程安全更新 UI

    def __init__(self) -> None:
        super().__init__()
        self.runtime = get_runtime()
        self._fault_message = ""
        self._bogie_catalog = self._load_bogie_catalog()
        self.workflow_instances: list[dict[str, object]] = []
        self._db_jobs: dict[str, dict[str, object]] = {}
        self.current_workflow_id: str | None = None
        self._build_ui()
        self._reload_bogie_options()
        self._load_workflow_list()
        self._refresh_status_bar()
        self._plc_poll.connect(self._apply_plc_poll)
        self._subscribe()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._unsubscribe()
        self.shutdown()
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if hasattr(self, "workflow_list"):
            self._load_workflow_list()

    def shutdown(self) -> None:
        self.workflow_panel.shutdown()

    def _subscribe(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            return
        self._broker_subscriptions = [
            broker.subscribe("plc_poll", self._on_plc_poll),
            broker.subscribe("plc_emc_stop", self._on_plc_emc),
        ]

    def _unsubscribe(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            return
        for subscription in getattr(self, "_broker_subscriptions", []):
            broker.unsubscribe(subscription)
        self._broker_subscriptions.clear()

    def _on_plc_poll(self, **payload) -> None:
        """plc_poll 回调（运行在发布者线程中），发射信号到主线程执行 UI 更新"""
        self._plc_poll.emit()

    def _on_plc_emc(self, **payload) -> None:
        self._stop_workflow()

    def _apply_plc_poll(self) -> None:
        """主线程安全地刷新 dashboard 数据"""
        self._dashboard.refresh_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        # 顶部状态 Dashboard
        self._dashboard = StatusDashboard(self)
        root.addWidget(self._dashboard)
        # 下方左右布局
        content = QHBoxLayout()
        content.setSpacing(6)
        content.addWidget(self._build_flow_panel(), 1)
        content.addWidget(self._build_monitor_panel(), 3)
        root.addLayout(content, 1)

    def _build_flow_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("flowControlPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        title = QLabel("流程编辑 / 控制区", panel)
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        meta_card = QFrame(panel)
        meta_card.setObjectName("anchorInfoCard")
        meta_layout = QVBoxLayout(meta_card)
        meta_layout.setContentsMargins(8, 8, 8, 8)
        meta_layout.setSpacing(4)
        meta_layout.addWidget(QLabel("流程实例参数", meta_card))
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)

        self.bogie_combo = QComboBox(meta_card)
        self.bogie_combo.currentTextChanged.connect(self._reload_position_options)
        form.addRow("车型:", self.bogie_combo)

        self.position_combo = QComboBox(meta_card)
        self.position_combo.currentTextChanged.connect(self._reload_flow_options)
        form.addRow("位号:", self.position_combo)

        self.flow_combo = QComboBox(meta_card)
        form.addRow("流程:", self.flow_combo)

        self.car_no_edit = QLineEdit(meta_card)
        self.car_no_edit.setPlaceholderText("请输入车号")
        form.addRow("车号:", self.car_no_edit)

        self.axle_no_edit = QLineEdit(meta_card)
        self.axle_no_edit.setPlaceholderText("请输入编号")
        form.addRow("编号:", self.axle_no_edit)

        meta_layout.addLayout(form)
        layout.addWidget(meta_card)
        self.current_flow_label = QLabel("当前工单: -", panel)
        layout.addWidget(self.current_flow_label)
        action_row = QHBoxLayout()
        self.create_flow_btn = QPushButton("创建工单", panel)
        self.delete_flow_btn = QPushButton("删除工单", panel)
        self.create_flow_btn.clicked.connect(self._create_workflow)
        self.delete_flow_btn.clicked.connect(self._delete_current_workflow)
        action_row.addWidget(self.create_flow_btn)
        action_row.addWidget(self.delete_flow_btn)
        layout.addLayout(action_row)
        layout.addWidget(QLabel("当前工单", panel))
        self.workflow_list = QTableWidget(0, 4, panel)
        self.workflow_list.setHorizontalHeaderLabels(["工作流名称", "创建者", "时间", "状态"])
        self.workflow_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.workflow_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.workflow_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.workflow_list.verticalHeader().setVisible(False)
        header = self.workflow_list.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.workflow_list.setColumnWidth(0, 160)
        self.workflow_list.setColumnWidth(1, 70)
        self.workflow_list.setColumnWidth(2, 120)
        self.workflow_list.setColumnWidth(3, 110)
        self.workflow_list.currentItemChanged.connect(self._switch_workflow)
        layout.addWidget(self.workflow_list, 1)
        run_row = QHBoxLayout()
        self.start_flow_btn = QPushButton("开始试验", panel)
        self.stop_flow_btn = QPushButton("停止试验", panel)
        self.select_cmd_btn = QPushButton("选择指令", panel)
        self.stop_flow_btn.setEnabled(False)
        self.select_cmd_btn.setEnabled(False)
        self.start_flow_btn.clicked.connect(self._start_workflow)
        self.stop_flow_btn.clicked.connect(self._stop_workflow)
        self.select_cmd_btn.clicked.connect(self._reopen_selection)
        run_row.addWidget(self.start_flow_btn)
        run_row.addWidget(self.stop_flow_btn)
        run_row.addWidget(self.select_cmd_btn)
        layout.addLayout(run_row)
        return panel

    def _build_monitor_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("tableCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        # title = QLabel("流程运行监控", panel)
        # title.setObjectName("cardTitle")
        # title_row.addWidget(title)
        title_row.addStretch(1)
        self._view_toggle_btn = QToolButton(panel)
        self._view_toggle_btn.setText("切换到表格视图")
        self._view_toggle_btn.setCheckable(True)
        self._view_toggle_btn.setChecked(False)
        self._view_toggle_btn.clicked.connect(self._on_view_toggle)
        title_row.addWidget(self._view_toggle_btn)
        layout.addLayout(title_row)
        self._flow_graph = FlowGraph()
        layout.addWidget(self._flow_graph, 1)
        self.workflow_panel = WorkflowRuntimePanel(panel, show_title=False, show_controls=False, show_data=True, flow_graph=self._flow_graph)
        self.workflow_panel.state_changed.connect(self._on_workflow_state_changed)
        self.workflow_panel.running_changed.connect(self._on_workflow_running_changed)
        self.workflow_panel.setVisible(False)
        layout.addWidget(self.workflow_panel, 1)
        return panel

    def _on_view_toggle(self, checked: bool) -> None:
        if checked:
            self._flow_graph.setVisible(False)
            self.workflow_panel.setVisible(True)
            self._view_toggle_btn.setText("切换到流程图")
        else:
            self._flow_graph.setVisible(True)
            self.workflow_panel.setVisible(False)
            self._view_toggle_btn.setText("切换到表格视图")

    def _load_bogie_catalog(self) -> dict[str, dict[str, object]]:
        bogie_path = get_runtime()["paths"]["bogie_config"]
        payload = json.loads(bogie_path.read_text(encoding="utf-8"))
        return {str(key): value for key, value in payload.items() if isinstance(value, dict) and str(key) != "车型"}

    def _reload_bogie_options(self) -> None:
        current_bogie = self.bogie_combo.currentText()
        self.bogie_combo.blockSignals(True)
        self.bogie_combo.clear()
        self.bogie_combo.addItems(sorted(self._bogie_catalog.keys()))
        if current_bogie:
            index = self.bogie_combo.findText(current_bogie)
            if index >= 0:
                self.bogie_combo.setCurrentIndex(index)
        self.bogie_combo.blockSignals(False)
        self._reload_position_options()

    def _reload_position_options(self) -> None:
        bogie_name = self.bogie_combo.currentText().strip()
        positions: list[str] = []
        if bogie_name:
            bogie_entry = self._bogie_catalog.get(bogie_name, {})
            positions = [str(key) for key, value in bogie_entry.items() if isinstance(value, dict)]
        current_position = self.position_combo.currentText()

        self.position_combo.blockSignals(True)
        self.position_combo.clear()
        self.position_combo.addItems(sorted(positions))
        if current_position:
            index = self.position_combo.findText(current_position)
            if index >= 0:
                self.position_combo.setCurrentIndex(index)
        self.position_combo.blockSignals(False)
        self._reload_flow_options()

    def _reload_flow_options(self) -> None:
        flow_dir = get_runtime()["paths"]["flow_dir"]
        flows: list[str] = [
            file.stem for file in flow_dir.glob("*.json") if file.name != "nodes.json"
        ]

        current_flow = self.flow_combo.currentText()
        self.flow_combo.blockSignals(True)
        self.flow_combo.clear()
        self.flow_combo.addItems(sorted(flows))
        if current_flow:
            index = self.flow_combo.findText(current_flow)
            if index >= 0:
                self.flow_combo.setCurrentIndex(index)
        self.flow_combo.blockSignals(False)

    def _build_workflow_from_template(self, meta_override=None, job_id=None, job_ctime=None):

        if meta_override is not None:
            bogie_type = str(meta_override.get("车型") or "").strip()
            bogie_pos = str(meta_override.get("位号") or "").strip()
            bogie_flow = str(meta_override.get("流程") or "").strip()
            train_no = str(meta_override.get("车号") or "").strip()
            axle_no = str(meta_override.get("编号") or "").strip()
        else:
            bogie_type = self.bogie_combo.currentText().strip()
            bogie_pos = self.position_combo.currentText().strip()
            bogie_flow = self.flow_combo.currentText().strip()
            train_no = self.car_no_edit.text().strip()
            axle_no = self.axle_no_edit.text().strip()
        if not bogie_type:
            raise ValueError("车型不能为空")
        if not bogie_pos:
            raise ValueError("位号不能为空")
        if not bogie_flow:
            raise ValueError("流程不能为空")
        if not train_no:
            raise ValueError("车号不能为空")
        if not axle_no:
            axle_no = "ID"

        if meta_override is not None:
            meta = {
                "车型": bogie_type,
                "位号": bogie_pos,
                "流程": bogie_flow,
                "车号": train_no,
                "编号": axle_no,
                "用户": str(meta_override.get("用户") or ""),
                "互检员": str(meta_override.get("互检员") or ""),
            }
        else:
            meta = {
                "车型": bogie_type,
                "位号": bogie_pos,
                "流程": bogie_flow,
                "车号": train_no,
                "编号": axle_no,
                "用户": str(self.runtime.get("current_user") or ""),
                "互检员": "",
            }

        flow_path = self.runtime["paths"]["flow_dir"] / f"{bogie_flow}.json"
        if not flow_path.is_file():
            QMessageBox.warning(self, "错误", f"未找到试验流程模板: {flow_path.name}")
            return

        worflow_json = json.loads(flow_path.read_text(encoding="utf-8"))
        worflow_json = copy.deepcopy(worflow_json)
        now = datetime.now().isoformat(timespec="seconds")
        worflow_json["id"] = str(job_id) if job_id else str(uuid4())
        worflow_json["ctime"] = str(job_ctime) if job_ctime else now
        worflow_json["name"] = f"{meta['车型']}-{meta['位号']}-{meta['车号']}-{meta['编号']}-{bogie_flow}"
        worflow_json["meta"] = meta

        bogie_path = self.runtime["paths"]["bogie_config"]
        if not bogie_path.is_file():
            QMessageBox.warning(self, "错误", f"未找到转向架配置文件: {bogie_path.name}")
            return
        bogie_json = json.loads(bogie_path.read_text(encoding="utf-8"))
        try:
            _bogie_data = bogie_json[bogie_type][bogie_pos]
        except Exception as exc:
            QMessageBox.warning(self, "错误", f"未找到转向架配置:{bogie_type}-{bogie_pos}")
            return

        workflow = self.runtime["wf_lib"].Workflow(worflow_json, _bogie_data)
        # breakpoint() # 检查workflow的实例信息
        workflow._ui_node_rows = []
        workflow._ui_state = workflow.state.value
        workflow._ui_error_message = ""
        return workflow, flow_path

    def _find_workflow_instance(self, workflow_id: str | None) -> dict[str, object] | None:
        if workflow_id is None:
            return None
        for instance in self.workflow_instances:
            if str(instance["id"]) == workflow_id:
                return instance
        return None

    def _current_workflow_instance(self) -> dict[str, object] | None:
        return self._find_workflow_instance(self.current_workflow_id)

    def _apply_workflow_meta(self, meta_payload: object) -> None:
        if not isinstance(meta_payload, dict):
            return
        bogie_name = str(meta_payload.get("车型") or "").strip()
        position_name = str(meta_payload.get("位号") or "").strip()
        car_no = str(meta_payload.get("车号") or "").strip()
        axle_no = str(meta_payload.get("编号") or "").strip()
        if bogie_name:
            index = self.bogie_combo.findText(bogie_name)
            if index >= 0:
                self.bogie_combo.setCurrentIndex(index)
        self._reload_position_options()
        if position_name:
            index = self.position_combo.findText(position_name)
            if index >= 0:
                self.position_combo.setCurrentIndex(index)
        flow_name = str(meta_payload.get("流程") or "").strip()
        if flow_name:
            index = self.flow_combo.findText(flow_name)
            if index >= 0:
                self.flow_combo.setCurrentIndex(index)
        self.car_no_edit.setText(car_no)
        self.axle_no_edit.setText(axle_no)

    def _job_db_path(self) -> Path:
        return Path(self.runtime["paths"]["db"])

    def _refresh_db_jobs(self) -> None:
        """从作业库加载当天任务 (供左侧列表合并显示与状态判定)."""
        try:
            jobs = jobstore.list_jobs(
                self._job_db_path(), on_date=datetime.now().strftime("%Y-%m-%d")
            )
            self._db_jobs = {str(job["id"]): job for job in jobs}
        except Exception:
            logger.exception("加载当天作业记录失败")
            self._db_jobs = {}

    def _state_color(self, kind: str) -> QColor:
        return {
            "idle": QColor(158, 158, 158, 90),
            "running": QColor(33, 150, 243, 90),
            "done": QColor(76, 175, 80, 100),
            "unfinished": QColor(255, 152, 0, 110),
            "error": QColor(244, 67, 54, 120),
        }[kind]

    def _workflow_has_summary(self, workflow) -> bool:
        for entry in getattr(workflow, "logs", []) or []:
            if (
                isinstance(entry, dict)
                and entry.get("event") == "summary"
                and isinstance(entry.get("extra"), dict)
                and entry["extra"]
            ):
                return True
        job = self._db_jobs.get(str(workflow.id))
        return bool(job and job.get("summary"))

    def _instance_state_display(self, instance) -> tuple[str, QColor]:
        """内存中工单的显示状态: (状态文字, 行底色)."""
        workflow = instance["workflow"]
        state = workflow.state
        if state == WorkflowState.RUNNING:
            return "执行中", self._state_color("running")
        if state == WorkflowState.DONE:
            if self._workflow_has_summary(workflow):
                return "已完成", self._state_color("done")
            return "未完成(无结果)", self._state_color("unfinished")
        if state == WorkflowState.STOPPED:
            return "未完成(停止)", self._state_color("unfinished")
        if state == WorkflowState.ERROR:
            return "未完成(故障)", self._state_color("error")
        return "未开始", self._state_color("idle")

    def _job_state_display(self, job) -> tuple[str, QColor]:
        """作业库行的显示状态. 库里的"执行中"在本进程没有对应实例时是上次
        运行被中断的残留, 按未完成显示 (库存值不改)."""
        state = str(job.get("state") or "")
        if state == jobstore.STATE_DONE:
            if job.get("summary"):
                return "已完成", self._state_color("done")
            return "未完成(无结果)", self._state_color("unfinished")
        if state == jobstore.STATE_STOPPED:
            return "未完成(停止)", self._state_color("unfinished")
        if state == jobstore.STATE_ERROR:
            return "未完成(故障)", self._state_color("error")
        if state == jobstore.STATE_RUNNING:
            return "未完成(中断)", self._state_color("unfinished")
        return "未开始", self._state_color("idle")

    def _ordered_task_entries(self) -> list[dict[str, object]]:
        """合并内存工单与当天作业库行, 按创建时间排序的列表条目."""
        entries: list[dict[str, object]] = []
        seen: set[str] = set()
        for instance in self.workflow_instances:
            workflow_id = str(instance["id"])
            seen.add(workflow_id)
            entries.append(
                {"id": workflow_id, "instance": instance, "job": self._db_jobs.get(workflow_id)}
            )
        for job in self._db_jobs.values():
            job_id = str(job["id"])
            if job_id in seen:
                continue
            entries.append({"id": job_id, "instance": None, "job": job})

        def _sort_key(entry: dict[str, object]) -> str:
            instance = entry["instance"]
            if instance is not None:
                return str(instance["workflow"].ctime or "").replace("T", " ")
            job = entry["job"] or {}
            return str(job.get("created_at") or "")

        entries.sort(key=_sort_key)
        return entries

    def _rebuild_workflow_from_job(self, job) -> bool:
        """按作业库行的 meta 与原 id/创建时间重建未开始工单为可运行对象."""
        try:
            built = self._build_workflow_from_template(
                meta_override=dict(job.get("meta") or {}),
                job_id=str(job["id"]),
                job_ctime=str(job.get("created_at") or ""),
            )
            if not built:
                return False
            workflow, flow_path = built
        except Exception as exc:
            logger.exception("rebuild workflow from job failed")
            QMessageBox.warning(self, "加载工单失败", str(exc))
            return False
        workflow_id = str(workflow.id)
        self.workflow_instances.append(
            {"id": workflow_id, "workflow": workflow, "flow_path": flow_path}
        )
        self._set_current_workflow(workflow_id)
        self._load_workflow_list()
        self._flow_graph._build_ui()
        self._flow_graph.update(workflow)
        logger.info(f"从作业库恢复工单: Name={workflow.name}")
        return True

    def _refresh_workflow_actions(self) -> None:
        """按当前选中任务刷新开始/删除按钮: 只有未开始的工单可开始,
        只有从未开始过的工单可删除 (已产生记录的作业保留在库中)."""
        if not hasattr(self, "start_flow_btn"):
            return
        running = self.workflow_panel.is_running()
        instance = self._current_workflow_instance()
        startable = False
        deletable = False
        if instance is not None:
            state = instance["workflow"].state
            job = self._db_jobs.get(str(instance["id"]))
            startable = state == WorkflowState.IDLE
            deletable = state == WorkflowState.IDLE and not (job and job.get("started_at"))
        elif self.current_workflow_id is not None:
            job = self._db_jobs.get(str(self.current_workflow_id))
            if job is not None:
                deletable = (
                    str(job.get("state") or "") == jobstore.STATE_IDLE
                    and not job.get("started_at")
                )
        self.start_flow_btn.setEnabled(startable and not running)
        self.delete_flow_btn.setEnabled(deletable and not running)

    def _set_current_workflow(self, workflow_id: str | None) -> None:
        instance = self._find_workflow_instance(workflow_id)
        if instance is None and workflow_id is not None:
            self._refresh_db_jobs()
            job = self._db_jobs.get(str(workflow_id))
            if (
                job is not None
                and str(job.get("state") or "") == jobstore.STATE_IDLE
                and not job.get("started_at")
            ):
                # 未开始的当天工单: 按原 id 重建为可运行对象
                if self._rebuild_workflow_from_job(job):
                    return
                instance = self._find_workflow_instance(workflow_id)
        if instance is None:
            job = self._db_jobs.get(str(workflow_id)) if workflow_id is not None else None
            if job is None:
                self.current_workflow_id = None
                self.runtime["wf"] = None
                self.workflow_panel.set_workflow_instance(None)
                self._refresh_current_flow_label()
                self.workflow_panel._prefill_node_table([])
                self._refresh_workflow_actions()
                return
            # 已开始过的作业: 只读记录, 不重建、不允许再次启动
            self.current_workflow_id = str(job["id"])
            self.runtime["wf"] = None
            self.workflow_panel.set_workflow_instance(None)
            self._apply_workflow_meta(job.get("meta") or {})
            self._refresh_current_flow_label()
            self.workflow_panel._prefill_node_table([])
            self._refresh_workflow_actions()
            logger.info(f"查看作业记录: Name={job.get('name')}")
            return
        self.current_workflow_id = str(instance["id"])
        workflow = instance["workflow"]
        self.runtime["wf"] = workflow
        self.workflow_panel.set_workflow_instance(workflow)
        self._apply_workflow_meta(workflow.meta)
        self._refresh_current_flow_label()
        self.workflow_panel._prefill_node_table(workflow.get_node_list())
        self._refresh_workflow_actions()
        logger.info(f"流程切换: Name={workflow.name}")

    def _load_workflow_list(self) -> None:
        self._refresh_db_jobs()
        entries = self._ordered_task_entries()
        self.workflow_list.blockSignals(True)
        self.workflow_list.setRowCount(0)
        selected_row = -1
        for row_index, entry in enumerate(entries):
            instance = entry["instance"]
            job = entry["job"]
            if instance is not None:
                workflow = instance["workflow"]
                name = str(workflow.name or "当前流程")
                creator = str(workflow.meta.get("用户") or "")
                created = str(workflow.ctime or "").replace("T", " ")
                state_text, color = self._instance_state_display(instance)
                tooltip = str(instance["flow_path"]) if instance.get("flow_path") is not None else ""
            else:
                name = str(job.get("name") or "当前流程")
                creator = str(job.get("user") or "")
                created = str(job.get("created_at") or "")
                state_text, color = self._job_state_display(job)
                tooltip = ""
            self.workflow_list.insertRow(row_index)
            item = QTableWidgetItem(name)
            if tooltip:
                item.setToolTip(tooltip)
            item.setData(Qt.UserRole, entry["id"])
            creator_item = QTableWidgetItem(creator)
            created_item = QTableWidgetItem(created)
            state_item = QTableWidgetItem(state_text)
            brush = QBrush(color)
            for cell in (item, creator_item, created_item, state_item):
                cell.setBackground(brush)
            self.workflow_list.setItem(row_index, 0, item)
            self.workflow_list.setItem(row_index, 1, creator_item)
            self.workflow_list.setItem(row_index, 2, created_item)
            self.workflow_list.setItem(row_index, 3, state_item)
            if entry["id"] == self.current_workflow_id:
                selected_row = row_index
        if selected_row >= 0:
            self.workflow_list.setCurrentCell(selected_row, 0)
        self.workflow_list.blockSignals(False)
        self._refresh_current_flow_label()
        self._refresh_workflow_actions()

    def _switch_workflow(self, current: QTableWidgetItem | None, previous: QTableWidgetItem | None) -> None:
        del previous
        if current is None or self.workflow_panel.is_running():
            return
        id_item = self.workflow_list.item(current.row(), 0)
        if id_item is None:
            return
        self._set_current_workflow(str(id_item.data(Qt.UserRole)))
        self._set_fault("")

    def _refresh_current_flow_label(self) -> None:
        instance = self._current_workflow_instance()
        if instance is not None:
            name = str(instance["workflow"].name or "当前流程")
            self.current_flow_label.setText(f"当前流程: {name}")
            return
        if self.current_workflow_id is not None:
            job = self._db_jobs.get(str(self.current_workflow_id))
            if job is not None:
                state_text, _color = self._job_state_display(job)
                self.current_flow_label.setText(
                    f"当前流程: {job.get('name') or '当前流程'} ({state_text})"
                )
                return
        self.current_flow_label.setText("当前流程: -")

    def _create_workflow(self) -> None:
        if self.workflow_panel.is_running():
            return
        try:
            workflow, flow_path = self._build_workflow_from_template()
        except Exception as exc:
            logger.exception("create workflow failed")
            QMessageBox.warning(self, "创建流程失败", str(exc))
            return
        workflow_id = str(workflow.id)
        self.workflow_instances.append({"id": workflow_id, "workflow": workflow, "flow_path": flow_path})
        try:
            jobstore.create_job(
                self._job_db_path(),
                job_id=workflow_id,
                created_at=str(workflow.ctime or ""),
                name=str(workflow.name or ""),
                job_type=str(workflow.meta.get("流程") or ""),
                user=str(workflow.meta.get("用户") or ""),
                meta=dict(workflow.meta or {}),
            )
        except Exception:
            logger.exception("创建工单落库失败: Name=%s", workflow.name)
        self._set_current_workflow(workflow_id)
        self._load_workflow_list()
        self._set_fault("")
        self._flow_graph._build_ui()
        self._flow_graph.update(workflow)
        logger.info(f"创建流程: Name={workflow.name}")

    def _delete_current_workflow(self) -> None:
        if self.workflow_panel.is_running() or self.current_workflow_id is None:
            return
        target_id = str(self.current_workflow_id)
        entries = self._ordered_task_entries()
        entry = next((item for item in entries if item["id"] == target_id), None)
        if entry is None:
            return
        instance = entry["instance"]
        job = entry["job"]
        # 只允许删除从未开始过的工单; 已产生记录的作业保留在作业库中
        if instance is not None and instance["workflow"].state != WorkflowState.IDLE:
            return
        if job is not None and (
            job.get("started_at") or str(job.get("state") or "") != jobstore.STATE_IDLE
        ):
            return
        try:
            jobstore.delete_job(self._job_db_path(), target_id)
        except Exception:
            logger.exception("删除工单作业记录失败: id=%s", target_id)
        self._db_jobs.pop(target_id, None)
        if instance is not None:
            self.workflow_instances.remove(instance)
        remaining_ids = [item["id"] for item in entries if item["id"] != target_id]
        next_workflow_id: str | None = None
        if remaining_ids:
            deleted_index = [item["id"] for item in entries].index(target_id)
            next_workflow_id = remaining_ids[min(deleted_index, len(remaining_ids) - 1)]
        self._set_current_workflow(next_workflow_id)
        self._load_workflow_list()

    def _current_fault_message(self) -> str:
        return self._fault_message

    def _refresh_status_bar(self) -> None:
        sink = self.runtime.get("status_sink")
        if callable(sink):
            sink(fault_message=self._current_fault_message())

    def _set_fault(self, message: str) -> None:
        self._fault_message = message
        self._refresh_status_bar()

    def _on_workflow_running_changed(self, running: bool) -> None:
        self.create_flow_btn.setEnabled(not running)
        self.workflow_list.setEnabled(not running)
        self.stop_flow_btn.setEnabled(running)
        self.select_cmd_btn.setEnabled(running)
        self._refresh_workflow_actions()
        self._refresh_status_bar()

    def _on_workflow_state_changed(self, state: str, error_message: str) -> None:
        if state == "error":
            self._set_fault(error_message or "流程执行错误")
        elif state == "stopped":
            self._set_fault("流程已停止")
        else:
            self._set_fault("")
        self._load_workflow_list()

    def _start_workflow(self) -> None:
        instance = self._current_workflow_instance()
        if instance is None:
            return
        # 已开始过的工单 (含已完成/停止/故障) 不允许从列表再次启动,
        # 避免同一条作业记录被重复运行覆盖
        if instance["workflow"].state != WorkflowState.IDLE:
            return
        self.workflow_panel.start_workflow()

    def _stop_workflow(self) -> None:
        self.workflow_panel.stop_workflow()

    def _reopen_selection(self) -> None:
        runner = self.workflow_panel.runner
        if runner is not None and runner.isRunning():
            runner.reopen_select()
