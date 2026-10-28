"""push 包共享基础: 异常类 + config/runtime 访问器.

iot.py 与 emis.py 都会用到这些基础工具, 集中放在本模块,
避免两个业务模块互相 import, 保持"功能完全不同".
"""

from __future__ import annotations

import json
import logging
from typing import Any

from _runtime import get_runtime

logger = logging.getLogger(__name__)


class PushError(RuntimeError):
    """推送相关错误基类: 消息面向用户展示, 同时已写入当天日志.

    继承 RuntimeError, 历史调用方 (except RuntimeError) 无需修改即可捕获.
    """


class PushConfigError(PushError):
    """推送配置文件 (runtime/push/config.json) 不存在或格式错误."""


def _push_config_path() -> Any:
    """push config.json 的路径 (来自 runtime.paths.push_config)."""
    return get_runtime()["paths"]["push_config"]


def _load_push_config() -> dict:
    """加载 push config.json, 路径由 runtime.paths.push_config 提供.

    失败时: 错误详情写入当天日志, 并抛 PushConfigError (消息含文件路径与出错行列).
    """
    path = _push_config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        msg = f"推送配置文件不存在: {path}"
        logger.error(msg)
        raise PushConfigError(msg) from exc
    except json.JSONDecodeError as exc:
        # 摘出出错那一行的原文, 便于直接定位编辑错误
        lines = exc.doc.splitlines()
        bad_line = (
            lines[exc.lineno - 1].strip() if 0 < exc.lineno <= len(lines) else ""
        )
        msg = (
            f"推送配置 JSON 格式错误: {path}\n"
            f"  第 {exc.lineno} 行 第 {exc.colno} 列: {exc.msg}\n"
            f"  出错内容: {bad_line}"
        )
        logger.error("%s", msg)
        raise PushConfigError(msg) from exc
    except OSError as exc:
        msg = f"推送配置文件无法读取: {path} ({exc})"
        logger.error(msg)
        raise PushConfigError(msg) from exc


def _get_workflow() -> Any:
    return get_runtime().get("wf")


def _get_bed() -> dict:
    return get_runtime().get("bed_data") or {}


def _get_meta(wf: Any) -> dict:
    if wf is None:
        return {}
    return getattr(wf, "meta", {}) or {}
