from __future__ import annotations

from pathlib import Path
import logging

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget, QPushButton

from _runtime import bed_section, get_runtime
from ui.dialog_fit.view import Window as FitDialog

from ._view import Ui_Form
import logging


class Window(QWidget):
    runtime_event = Signal(dict)

    BASEPOS_X = (
        "称重台X位移1",
        "称重台X位移2",
        "称重台X位移3",
        "称重台X位移4",
    )
    BASEPOS_NC = (
        "车轮内侧距1",
        "车轮内侧距2",
        "车轮内侧距3",
        "车轮内侧距4",
    )
    WEIGHTS = (
        "轮重测量1",
        "轮重测量2",
        "轮重测量3",
        "轮重测量4",
    )
    HEAD_POS_H = (
        "加载头横向位移1",
        "加载头横向位移2",
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.runtime = get_runtime()
        self._plc = self.runtime.get("plc")
        self._vsp = self.runtime.get("vsp")
        self.ui = Ui_Form()
        self.ui.setupUi(self)
        self.runtime_event.connect(self._apply_runtime_event)
        self.ui.rd_sensor.toggled.connect(lambda checked: self._toggle_view("sensor"))
        self.ui.rd_cal.toggled.connect(lambda checked: self._toggle_view("cal"))
        self._broker_subscriptions: list[object] = []
        self._apply_flexible_size()
        self._build_ui()
        self._on_user_changed()
        self._subscribe()
        self.update_plc_ui()
        self._toggle_view("sensor")

    def _on_user_changed(self, **payload) -> None:
        ctrls = self.findChildren(QPushButton)
        user = self.runtime.get("cur_user").get('username')
        if user=="admin":
            for btn in ctrls:
                btn.setVisible(True)
        else:
            for btn in ctrls:
                btn.setVisible(False)

    def _apply_flexible_size(self) -> None:
        """覆盖 _view.py 中的固定尺寸设置，允许自适应"""
        # 设置 size policy 为 Preferred + Expanding，允许自适应缩放
        size_policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setSizePolicy(size_policy)

        # 清除整个窗口的固定尺寸限制
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)  # QWIDGETSIZE_MAX

        # 清除 widget_2 的过大最小尺寸限制，但保留一个合理的最小尺寸
        if hasattr(self.ui, "widget_2"):
            self.ui.widget_2.setMinimumSize(1100, 800)  # 设置合理的最小尺寸

        if hasattr(self.ui, "lb_bg"):
            self.ui.lb_bg.setMinimumSize(0, 0)
            self.ui.lb_bg.setScaledContents(True)

    def _build_ui(self) -> None:
        # 不使用 setFixedSize，让窗口可以自适应
        self._load_background_image()
        self._bind_fit_double_click()

    def _toggle_view(self, view_type):
        if view_type=="sensor":
            print("传感器视图")
            ctrls = self.findChildren(QLabel)
            for lbl in ctrls:
                lbl.show()
                obj_type = lbl.whatsThis()
                if 'caled' in obj_type:
                    lbl.hide()

        if view_type=="cal":
            print("计算视图")
            ctrls = self.findChildren(QLabel)
            for lbl in ctrls:
                lbl.show()
                obj_type = lbl.whatsThis()
                if 'sensor' in obj_type:
                    lbl.hide()

    def _background_label(self) -> QLabel | None:
        return getattr(self.ui, "lb_bg", None) or getattr(self.ui, "label", None)

    def _load_background_image(self) -> None:
        bg_label = self._background_label()
        if bg_label is None:
            return

        image_path = Path(self.runtime["base_dir"]) / "runtime" / "res" / "image" / "dim.png"
        pixmap = QPixmap(str(image_path.resolve()))
        if pixmap.isNull():
            bg_label.clear()
            return

        bg_label.setPixmap(pixmap)
        bg_label.setScaledContents(True)

    def _bind_fit_double_click(self) -> None:
        for label in self.findChildren(QLabel):
            if label is self._background_label():
                continue
            label.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if isinstance(watched, QLabel) and event.type() == QEvent.MouseButtonDblClick:
            self.on_dbclick_fit(watched)
            return True
        return super().eventFilter(watched, event)

    def on_dbclick_fit(self, label: QLabel) -> None:
        pt_name = label.text().strip()
        if not pt_name:
            return

        pt_type = self._resolve_pt_type(pt_name)
        if pt_type is None:
            return

        dialog = FitDialog(pt_type=pt_type, pt_name=pt_name, parent=self)
        dialog.exec()

    def _resolve_pt_type(self, pt_name: str) -> str | None:
        if self._plc is not None and pt_name in getattr(self._plc, "points", {}):
            return "plc"
        if self._vsp is not None and pt_name in getattr(self._vsp, "points", {}):
            return "vsp"
        return None

    def _subscribe(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            return
        self._broker_subscriptions = [
            broker.subscribe("plc_poll", self._on_plc_poll),
            # broker.subscribe("vsp_poll", self._on_vsp_poll),
            broker.subscribe("cal_data", self._on_cal_data),
            broker.subscribe("user_changed", self._on_user_changed),
        ]

    def _unsubscribe(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            self._broker_subscriptions.clear()
            return
        for subscription in self._broker_subscriptions:
            broker.unsubscribe(subscription)
        self._broker_subscriptions.clear()

    def _on_plc_poll(self, **payload) -> None:
        self.runtime_event.emit({"topic": "plc_poll", **payload})

    def _on_cal_data(self, **payload) -> None:
        self.runtime_event.emit({"topic": "cal_data", **payload})

    def _apply_runtime_event(self, payload: dict) -> None:
        if payload.get("topic") == "plc_poll":
            self.update_plc_ui()
        elif payload.get("topic") == "cal_data":
            self.update_cal_data(payload=payload)
        else:
            return

    def update_plc_ui(self, **payload) -> None:
        try:
            bench_x_values = [self._read_plc_value(name) for name in self.BASEPOS_X]
            bench_y_values = [self._read_plc_value(name) for name in self.BASEPOS_NC]
            bench_w_values = [self._read_plc_value(name) for name in self.WEIGHTS]
            head_move_values = [self._read_plc_value(name) for name in self.HEAD_POS_H]

            self._set_label_value(self.ui.bench1_x, bench_x_values[0])
            self._set_label_value(self.ui.bench2_x, bench_x_values[1])
            self._set_label_value(self.ui.bench3_x, bench_x_values[2])
            self._set_label_value(self.ui.bench4_x, bench_x_values[3])

            self._set_label_value(self.ui.bench1_y, bench_y_values[0])
            self._set_label_value(self.ui.bench2_y, bench_y_values[1])
            self._set_label_value(self.ui.bench3_y, bench_y_values[2])
            self._set_label_value(self.ui.bench4_y, bench_y_values[3])

            self._set_label_value(self.ui.bench1_w, bench_w_values[0])
            self._set_label_value(self.ui.bench2_w, bench_w_values[1])
            self._set_label_value(self.ui.bench3_w, bench_w_values[2])
            self._set_label_value(self.ui.bench4_w, bench_w_values[3])

            # self._set_label_value(self.ui.head13_move, head_move_values[0])
            # self._set_label_value(self.ui.head24_move, head_move_values[1])

            # 更新plc数据
            # self._set_label_value(self.ui.head13_y, self._read_plc_value("加载头垂向位移1"))
            # self._set_label_value(self.ui.head24_y, self._read_plc_value("加载头垂向位移2"))

            cur_flow_data = self.runtime.get("wf")
            if cur_flow_data:
                # 原点位置只与试验台有关、与车型无关，统一从 bed 读
                base_pos = bed_section("原点位置")
                bogie_spec = cur_flow_data.data["转向架数据"]

                _data13 = (bench_x_values[0]-base_pos["滑台位移1"]) + (bench_x_values[2]-base_pos["滑台位移3"]) + bogie_spec["轴距"]
                _data24 = (bench_x_values[1]-base_pos["滑台位移2"]) + (bench_x_values[3]-base_pos["滑台位移4"]) + bogie_spec["轴距"]
                _data12 = (bench_y_values[0]-base_pos["滑台内测距1"]) + (bench_y_values[1]-base_pos["滑台内测距2"]) + bogie_spec["内侧距"]
                _data34 = (bench_y_values[2]-base_pos["滑台内测距3"]) + (bench_y_values[3]-base_pos["滑台内测距4"]) + bogie_spec["内侧距"]

                self._set_label_value(self.ui.l24_cal, round(_data24,3))
                self._set_label_value(self.ui.l13_cal, round(_data13,3))
                self._set_label_value(self.ui.w12_cal, round(_data12,3))
                self._set_label_value(self.ui.w34_cal, round(_data34,3))

                _data = bench_w_values[0]
                self._set_label_value(self.ui.bench1_dw_cal, round(_data,3))
                _data = bench_w_values[1]
                self._set_label_value(self.ui.bench2_dw_cal, round(_data,3))
                _data = bench_w_values[2]
                self._set_label_value(self.ui.bench3_dw_cal, round(_data,3))
                _data = bench_w_values[3]
                self._set_label_value(self.ui.bench4_dw_cal, round(_data,3))

                _data = bench_w_values[0] + bench_w_values[1]
                self._set_label_value(self.ui.axis12_w_cal, round(_data,3))

                _data = bench_w_values[2] + bench_w_values[3]
                self._set_label_value(self.ui.axis34_w_cal, round(_data,3))

                # self._set_label_value(self.ui.hang1_cal, round(_data,3))
                # self._set_label_value(self.ui.hang2_cal, round(_data,3))

        except Exception as e:
            print(e)


    def update_cal_data(self, **payload) -> None:
        data = payload['payload']["data"]
        self._set_label_value(self.ui.l24_cal, data["2-4位轴距"]["测量值"])
        self._set_label_value(self.ui.l13_cal, data["1-3位轴距"]["测量值"])
        self._set_label_value(self.ui.w12_cal, data["12内侧距"]["测量值"])
        self._set_label_value(self.ui.w34_cal, data["34内侧距"]["测量值"])

        self._set_label_value(self.ui.bench1_dw_cal, data["1位轮重差"]["测量值"])
        self._set_label_value(self.ui.bench2_dw_cal, data["2位轮重差"]["测量值"])
        self._set_label_value(self.ui.bench3_dw_cal, data["3位轮重差"]["测量值"])
        self._set_label_value(self.ui.bench4_dw_cal, data["4位轮重差"]["测量值"])

        self._set_label_value(self.ui.axis12_w_cal, data["1-2位轴重"]["测量值"])
        self._set_label_value(self.ui.axis34_w_cal, data["3-4位轴重"]["测量值"])

        self._set_label_value(self.ui.hang1_cal, data["1位二系悬挂高度"]["测量值"])
        self._set_label_value(self.ui.hang2_cal, data["2位二系悬挂高度"]["测量值"])


    def _read_vsp_value(self, name: str) -> float | None:
        if self._vsp is None:
            return None
        try:
            value = self._vsp.read(name)
        except KeyError:
            return None
        return float(value) if isinstance(value, (int, float)) else None

    def _read_plc_value(self, name: str) -> float | None:
        if self._plc is None:
            return None
        if self._plc.alive == False:
            return None
        try:
            value = self._plc.read(name)
        except Exception as e:
            logging.error(f"读取PLC数据失败: {e}")
            return None
        return float(value) if isinstance(value, (int, float)) else None

    def _set_label_value(self, label: QLabel, value: float | None) -> None:
        label.setText("-" if value is None else str(value))

    def _sum_values(self, left: float | None, right: float | None) -> float | None:
        if left is None or right is None:
            return None
        return left + right

    def closeEvent(self, event) -> None:
        self._unsubscribe()
        super().closeEvent(event)
