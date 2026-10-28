from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # pragma: no cover
    QWebEngineView = None


FLOW_URL = "http://localhost:82"


class Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        # 设置 size policy 为 Expander，允许自适应缩放
        size_policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setSizePolicy(size_policy)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if QWebEngineView is None:
            fallback = QLabel(f"当前环境未安装 Qt WebEngine，无法打开 {FLOW_URL}", self)
            fallback.setWordWrap(True)
            fallback.setMargin(24)
            layout.addWidget(fallback)
            return

        self.browser = QWebEngineView(self)
        self.browser.setUrl(QUrl(FLOW_URL))
        layout.addWidget(self.browser)
