from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTextBrowser,
    QVBoxLayout,
)

from _runtime import get_runtime

logger = logging.getLogger(__name__)

# 使用说明单文件 HTML（截图已内嵌），放在 runtime/help 下，
# 打包脚本会整目录拷贝 runtime，装机后路径不变。
_MANUAL_REL = Path("runtime") / "help" / "user_manual.html"


def _manual_path() -> Path:
    try:
        base_dir = Path(get_runtime()["base_dir"])
    except Exception:
        base_dir = Path(__file__).resolve().parents[2]
    return base_dir / _MANUAL_REL


class Window(QDialog):
    """帮助 → 使用说明：加载 runtime/help/user_manual.html 并渲染。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("使用说明")
        self.setModal(True)
        self.resize(1020, 780)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(True)
        layout.addWidget(self.browser, 1)
        self._load_manual()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _load_manual(self) -> None:
        path = _manual_path()
        if path.is_file():
            try:
                self.browser.setHtml(path.read_text(encoding="utf-8"))
                return
            except Exception:
                logger.exception("加载使用说明失败: %s", path)
        logger.warning("使用说明文件缺失: %s", path)
        self.browser.setPlainText(
            "使用说明文件缺失。\n\n"
            f"应位于：{path}\n"
            "请确认程序安装完整，或联系维护人员。"
        )
