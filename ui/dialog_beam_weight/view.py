from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout

from _runtime import get_bed_data, get_runtime

logger = logging.getLogger(__name__)

# 需要按横梁自重修正 segs 的点位: 两个加载装置各承担横梁自重的一半
TARGET_POINTS = ("加载压力1", "加载压力2")


def compute_segs(segs_raw: list, half_weight: float) -> list[str]:
    """由标准映射 segs_raw 生成实际 segs。

    第一组 (零点, 如 4000@0) 原样保留, 其余每组的映射值 (target) 加上
    half_weight (横梁自重的一半); 源值 (source) 不变。
    """
    result: list[str] = []
    for index, item in enumerate(segs_raw):
        text = str(item).strip()
        source_text, sep, target_text = text.partition("@")
        if not sep:
            raise ValueError(f"segs_raw 格式非法: {item!r}")
        float(source_text)  # 源值也必须是数字, 与 SegmentMapping.parse 口径一致
        target = float(target_text)
        if index == 0:
            result.append(text)
        else:
            result.append(f"{source_text.strip()}@{target + half_weight:g}")
    return result


class Window(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("横梁自重修正")
        self.setModal(True)
        self.setMinimumWidth(320)
        self._weight = self._read_weight()
        self._build_ui()

    @staticmethod
    def _read_weight() -> float | None:
        raw = get_bed_data().get("横梁自重")
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        text = f"横梁自重: {self._weight:g}" if self._weight is not None else "横梁自重: 未配置"
        self.weight_label = QLabel(text, self)
        self.weight_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.weight_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(self.weight_label)

        self.apply_btn = QPushButton("设定", self)
        self.apply_btn.clicked.connect(self._on_apply)
        root.addWidget(self.apply_btn)

    def _on_apply(self) -> None:
        if self._weight is None:
            QMessageBox.warning(self, "横梁自重修正", "bed.json 未配置「横梁自重」, 无法设定。")
            return

        runtime = get_runtime()
        config_path = Path(runtime["paths"]["plc_config"])
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        raw_points = payload.get("pts") or {}

        # 两个点位先都算好并校验通过, 再统一落盘, 避免只改一半
        planned: dict[str, list[str]] = {}
        for name in TARGET_POINTS:
            point = raw_points.get(name)
            if point is None:
                QMessageBox.warning(self, "横梁自重修正", f"plc.json 中没有点位「{name}」。")
                return
            segs_raw = point.get("segs_raw")
            if not isinstance(segs_raw, list) or not segs_raw:
                QMessageBox.warning(
                    self, "横梁自重修正", f"点位「{name}」没有 segs_raw 标准映射, 无法设定。"
                )
                return
            try:
                planned[name] = compute_segs(segs_raw, self._weight / 2)
            except (TypeError, ValueError) as exc:
                QMessageBox.warning(self, "横梁自重修正", f"点位「{name}」segs_raw 解析失败: {exc}")
                return

        table = runtime.get("plc")
        try:
            if table is not None:
                # 与标定弹窗同一条写回路径: 改文件 + 替换运行中的点位对象
                for name, segs in planned.items():
                    table.update_by_id(name, segs=segs)
            else:
                for name, segs in planned.items():
                    raw_points[name]["segs"] = segs
                config_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        except Exception as exc:
            QMessageBox.warning(self, "横梁自重修正", f"写回 plc.json 失败: {exc}")
            return

        logger.info(
            "横梁自重修正: 横梁自重=%s, 已更新 %s 的 segs 并写回 plc.json",
            self._weight,
            "/".join(TARGET_POINTS),
        )
        QMessageBox.information(
            self,
            "横梁自重修正",
            f"已按横梁自重 {self._weight:g} 更新 {'、'.join(TARGET_POINTS)} 的 segs, 并写回 plc.json。",
        )
        self.accept()
