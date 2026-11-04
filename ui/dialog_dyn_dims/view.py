from __future__ import annotations

from pathlib import Path
import json
import logging

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget, QPushButton

from _runtime import bed_section, get_runtime, reload_bed_data
from ui.dialog_fit.view import Window as FitDialog

from ._view import Ui_Form

logger = logging.getLogger(__name__)


class Window(QWidget):
    runtime_event = Signal(dict)

    BASEPOS_ZJ = (
        "称重台位移1",
        "称重台位移2",
        "称重台位移3",
        "称重台位移4",
    )
    BASEPOS_NCJ = (
        "内测距激光1",
        "内测距激光2",
        "内测距激光3",
        "内测距激光4",
    )
    WEIGHTS = (
        "称重台1",
        "称重台2",
        "称重台3",
        "称重台4",
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
        self._can = self.runtime.get("can")
        self.ui = Ui_Form()
        self.ui.setupUi(self)
        self.runtime_event.connect(self._apply_runtime_event)
        self.ui.btn_origin.clicked.connect(self._zero_origin)
        self._broker_subscriptions: list[object] = []
        self._apply_flexible_size()
        self._build_ui()
        self._on_user_changed()
        self._subscribe()
        self.update_dim()
        
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
            broker.subscribe("plc_poll", self._on_vsp_poll),
            broker.subscribe("can_poll", self._on_can_poll),
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

    def _on_vsp_poll(self, **payload) -> None:
        self.runtime_event.emit({"topic": "plc_poll", **payload})

    def _on_can_poll(self, **payload) -> None:
        self.runtime_event.emit({"topic": "can_poll", **payload})

    def _on_cal_data(self, **payload) -> None:
        self.runtime_event.emit({"topic": "cal_data", **payload})

    def _apply_runtime_event(self, payload: dict) -> None:
        if payload.get("topic") == "plc_poll":
            pass
        elif payload.get("topic") == "can_poll":
            self.update_dim()
        else:
            return

    def update_dim(self, **payload) -> None:
        """CAN 来源的实时值: 称重台位移1~4, 并刷新依赖它的 1-3/2-4 位轴距."""
        try:
            bench_ncj_values = [self._read_vsp_value(name) for name in self.BASEPOS_NCJ]
            self._set_label_value(self.ui.bench1_ncj, bench_ncj_values[0])
            self._set_label_value(self.ui.bench2_ncj, bench_ncj_values[1])
            self._set_label_value(self.ui.bench3_ncj, bench_ncj_values[2])
            self._set_label_value(self.ui.bench4_ncj, bench_ncj_values[3])

            bench_zj_values = [self._read_can_value(name) for name in self.BASEPOS_ZJ]
            self._set_label_value(self.ui.bench1_zj, bench_zj_values[0])
            self._set_label_value(self.ui.bench2_zj, bench_zj_values[1])
            self._set_label_value(self.ui.bench3_zj, bench_zj_values[2])
            self._set_label_value(self.ui.bench4_zj, bench_zj_values[3])

            bench_w_values = [self._read_vsp_value(name) for name in self.WEIGHTS]
            self._set_label_value(self.ui.bench1_w, bench_w_values[0])
            self._set_label_value(self.ui.bench2_w, bench_w_values[1])
            self._set_label_value(self.ui.bench3_w, bench_w_values[2])
            self._set_label_value(self.ui.bench4_w, bench_w_values[3])

            if any(
                None in values
                for values in (bench_ncj_values, bench_w_values, bench_zj_values)
            ):
                return

            base_zj_13 = 0
            base_zj_24 = 0
            base_ncj_12 = 0
            base_ncj_34 = 0

            cur_flow_data = self.runtime.get("wf")
            if not cur_flow_data:
                base_pos = bed_section("标定杆")
                base_zj_13 = base_pos["轴距13"]
                base_zj_24 = base_pos["轴距24"]
                base_ncj_12 = base_pos["内测距12"]
                base_ncj_34 = base_pos["内测距34"]
            else:
                bogie_spec = cur_flow_data.data["转向架数据"]
                base_zj_13 = bogie_spec["轴距13"]
                base_zj_24 = bogie_spec["轴距24"]
                base_ncj_12 = bogie_spec["内测距12"]
                base_ncj_34 = bogie_spec["内测距34"]

            _data13 = (bench_zj_values[0]) + (bench_zj_values[2]) + base_zj_13
            _data24 = (bench_zj_values[1]) + (bench_zj_values[3]) + base_zj_24
            _data12 = bench_ncj_values[0] + bench_ncj_values[1] + base_ncj_12
            _data34 = bench_ncj_values[2] + bench_ncj_values[3] + base_ncj_34

            self._set_label_value(self.ui.l13_cal, round(_data13,3))
            self._set_label_value(self.ui.l24_cal, round(_data24,3))
            self._set_label_value(self.ui.w12_cal, round(_data12,3))
            self._set_label_value(self.ui.w34_cal, round(_data34,3))

        except Exception:
            logger.exception("实时数据刷新失败")
        
    def _read_can_value(self, name: str) -> float | None:
        """读取 CAN 点表(称重台位移1~4)的换算后真值, 未启用/离线/无点时返回 None."""
        if self._can is None:
            return None
        if not getattr(self._can, "alive", False):
            return None
        try:
            value = self._can.read(name)
        except Exception as e:
            logging.error(f"读取CAN数据失败: {e}")
            return None
        return float(value) if isinstance(value, (int, float)) else None

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

    def closeEvent(self, event) -> None:
        self._unsubscribe()
        super().closeEvent(event)

    def _zero_origin(self) -> None:
        """用当前实时值设定 bed.json「原点位置」：滑台内测距1-4、滑台位移1-4，然后保存。"""
        bench_ncj_values = [self._read_vsp_value(name) for name in self.BASEPOS_NCJ]
        bench_zj_values = [self._read_can_value(name) for name in self.BASEPOS_ZJ]
        if any(None in values for values in (bench_ncj_values, bench_zj_values)):
            logger.warning("原点位置设定失败：存在离线点位，不写入原点配置")
            return

        bed_config_path = self.runtime["paths"]["bed_config"]
        with open(bed_config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        origin = data.setdefault("原点位置", {})
        for i, value in enumerate(bench_ncj_values, start=1):
            origin[f"滑台内测距{i}"] = round(value, 3)
        for i, value in enumerate(bench_zj_values, start=1):
            origin[f"滑台位移{i}"] = round(value, 3)

        with open(bed_config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        reload_bed_data()
        logger.info("原点位置已更新并写入 %s", bed_config_path)
     