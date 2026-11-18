"""运行时插件加载器.

扫描 ``BASE_DIR/runtime/plugin`` 下的 ``.py`` 文件, 每个文件是一个独立的
弹窗插件, 在程序启动时由打包后的完整环境 (PyInstaller 解压后的解释器)
直接导入, 无需重新编译整个程序. 宿主机自身的 Python 环境与此无关.

插件契约 (单个 ``.py`` 文件, 顶层定义):
    TITLE: str       菜单名; 缺失或为空时用文件名.
    ADMIN_ONLY: bool 仅管理员可打开; 缺省 False, 复用菜单分发的 admin 门.
    Window: QDialog 子类, 必须可零参构造; 运行时数据用 ``get_runtime()``
        自取, 与现有弹窗写法一致.

加载语义:
    * 目录不存在或为空 -> 返回空, 程序行为与无插件时完全一致.
    * ``_`` 开头的文件不作插件扫描 (可作同目录辅助模块, 插件可 import).
    * 单个插件加载/校验失败只记日志并跳过, 绝不抛错、绝不挡启动.
    * 插件目录追加到 ``sys.path`` 末尾: 插件可 import 同目录辅助模块;
      追加 (而非前插) 保证程序自有模块与标准库优先, 插件无法影子它们.

返回 ``(菜单项列表, views 字典)``, 调用方并入 ``ui_registry`` 后由主框架
的通用菜单/弹窗路径接管; 页面 id 统一加 ``plugin:`` 前缀, 不会撞现有 id.
"""
from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QDialog

logger = logging.getLogger(__name__)

PLUGIN_GROUP_TITLE = "插件"
VIEW_ID_PREFIX = "plugin:"


def default_plugin_dir() -> Path:
    """插件目录: exe 所在目录 (dev 下为仓库根目录) 下的 runtime/plugin."""
    from _runtime import get_runtime

    return Path(get_runtime()["base_dir"]) / "runtime" / "plugin"


def _load_module(path: Path) -> Any:
    """按文件路径导入一个插件模块, 模块名随机, 不占用任何包命名空间."""
    module_name = f"runtime_plugin_{uuid.uuid4().hex[:12]}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法为 {path} 创建模块 spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _validate_plugin(module: Any, path: Path) -> tuple[str, type, bool] | None:
    """校验插件契约, 返回 (菜单名, 弹窗类, 仅管理员), 不合格返回 None."""
    window_cls = getattr(module, "Window", None)
    if window_cls is None:
        logger.warning("插件 %s 缺少 Window 类, 已跳过", path.name)
        return None
    if not (inspect.isclass(window_cls) and issubclass(window_cls, QDialog)):
        logger.warning("插件 %s 的 Window 不是 QDialog 子类, 已跳过", path.name)
        return None
    title = getattr(module, "TITLE", None)
    if not isinstance(title, str) or not title.strip():
        title = path.stem
    admin_only = bool(getattr(module, "ADMIN_ONLY", False))
    return title.strip(), window_cls, admin_only


def load_plugin_entries(
    plugin_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """扫描并加载插件, 返回 (菜单项列表, views 字典).

    本函数自身不抛错: 目录解析失败也只记日志并返回空.
    """
    if plugin_dir is None:
        try:
            plugin_dir = default_plugin_dir()
        except Exception:
            logger.exception("解析插件目录失败")
            return [], {}
    plugin_dir = Path(plugin_dir)
    if not plugin_dir.is_dir():
        return [], {}

    dir_text = str(plugin_dir)
    if dir_text not in sys.path:
        sys.path.append(dir_text)

    menu_entries: list[dict[str, Any]] = []
    views: dict[str, dict[str, Any]] = {}
    for path in sorted(plugin_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            module = _load_module(path)
        except Exception:
            logger.exception("插件 %s 加载失败, 已跳过", path.name)
            continue
        try:
            validated = _validate_plugin(module, path)
        except Exception:
            logger.exception("插件 %s 校验失败, 已跳过", path.name)
            continue
        if validated is None:
            continue
        title, window_cls, admin_only = validated
        view_id = f"{VIEW_ID_PREFIX}{path.stem}"
        menu_entries.append(
            {
                "title": title,
                "icon": "info.png",
                "view_id": view_id,
                "pop": True,
                "fixed": False,
                "admin": admin_only,
            }
        )
        views[view_id] = {"title": title, "obj": window_cls}
        logger.info("插件已加载: %s (%s)", title, path.name)
    return menu_entries, views
