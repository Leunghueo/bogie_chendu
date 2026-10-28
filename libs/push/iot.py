"""IoT 状态周期推送服务.

由 `main.py` 在程序启动时按 `app.ini` 的 `[iot] enable_iot` 决定是否启用:

    enable_iot = true   -> 启动后台守护线程, 按 `push/config.json` 的
                           `iot.interval`(单位: 秒) 周期调用 `all.iot()` 推送
    enable_iot = false  -> 完全不创建推送线程

线程特点:
* 启动后立即推送一次, 之后每 `interval` 秒推送一次;
* 单次推送失败静默跳过 (all.iot() 内部不打印 Traceback/不写日志), 循环继续, 不会退出;
* 应用退出时由 main.py 调用 `stop()` 结束线程.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .all import PushConfigError, _load_push_config
from .all import iot as iot_push

logger = logging.getLogger(__name__)

# iot.interval 缺省值 (秒)
DEFAULT_INTERVAL = 5.0


def _resolve_interval(iot_cfg: dict[str, Any]) -> float:
    """从 iot 配置中解析发布间隔(秒), 非法值回落到 DEFAULT_INTERVAL."""
    raw = iot_cfg.get("interval", DEFAULT_INTERVAL)
    try:
        interval = float(raw)
    except (TypeError, ValueError):
        logger.warning("iot.interval 非法(%r), 使用默认 %.1f 秒", raw, DEFAULT_INTERVAL)
        return DEFAULT_INTERVAL
    if interval <= 0:
        logger.warning("iot.interval 必须为正数(%r), 使用默认 %.1f 秒", raw, DEFAULT_INTERVAL)
        return DEFAULT_INTERVAL
    return interval


def create_iot_pusher() -> "IotPusher | None":
    """按 push/config.json 的 iot 配置创建推送器.

    以下情况返回 None (不启动推送线程, 仅记录日志):
    * 配置文件不存在或格式错误;
    * iot.host 或 iot.pub 未配置.
    """
    try:
        cfg = _load_push_config()
    except PushConfigError as exc:
        logger.error("IoT 推送未启动: %s", exc)
        return None

    iot_cfg = cfg.get("iot") or {}
    if not str(iot_cfg.get("host") or "").strip():
        logger.warning("IoT 推送未启动: 未配置 iot.host")
        return None
    if not str(iot_cfg.get("pub") or "").strip():
        logger.warning("IoT 推送未启动: 未配置 iot.pub")
        return None

    return IotPusher(interval=_resolve_interval(iot_cfg))


class IotPusher:
    """在后台守护线程中按固定间隔循环推送 IoT 消息."""

    def __init__(self, interval: float = DEFAULT_INTERVAL) -> None:
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    def start(self) -> threading.Thread:
        """启动推送线程 (已启动则直接返回)."""
        if self._thread is not None and self._thread.is_alive():
            return self._thread
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="iot-pusher", daemon=True
        )
        self._thread.start()
        logger.info("IoT 推送线程已启动: 间隔 %.1f 秒", self.interval)
        return self._thread

    def stop(self, timeout: float | None = 2.0) -> None:
        """通知推送线程退出并等待其结束."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning("IoT 推送线程未能在 %s 秒内退出", timeout)
        self._thread = None
        logger.info("IoT 推送线程已停止")

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    # ------------------------------------------------------------------ #
    # 内部: 推送循环
    # ------------------------------------------------------------------ #

    def _run(self) -> None:
        while True:
            try:
                iot_push()
            except Exception:  # noqa: BLE001
                # all.iot() 正常情况静默返回, 这里仅作兜底, 保证循环不中断
                logger.debug("IoT 推送异常, 将在下个周期重试", exc_info=True)
            if self._stop_event.wait(self.interval):
                break
