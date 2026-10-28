from __future__ import annotations

import configparser
import sys
from pathlib import Path
from typing import Any
import json

import guard

RUNTIME: dict[str, Any] = {}

def init_runtime(**kwargs: Any) -> dict[str, Any]:
    RUNTIME.clear()
    RUNTIME.update(kwargs)
    return RUNTIME

def update_runtime(**kwargs: Any) -> dict[str, Any]:
    RUNTIME.update(kwargs)
    return RUNTIME

def get_runtime() -> dict[str, Any]:
    if not RUNTIME:
        raise RuntimeError("程序运行时未初始化")
    return RUNTIME

BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
config = configparser.ConfigParser()
config.read(BASE_DIR / "app.ini", encoding="utf-8")


def source_enabled(config: configparser.ConfigParser, section: str) -> bool:
    """plc/vsp/can 的总开关：app.ini 里 enable 优先，兼容旧的 used。

    两个字段都没有时默认开启（保持旧行为）；enable=false 时 main
    不创建该路的点表、也不启动轮询线程，runtime 里对应项为 None。
    """
    if config.has_option(section, "enable"):
        return config.getboolean(section, "enable")
    if config.has_option(section, "used"):
        return config.getboolean(section, "used")
    return True


sim = config.get("sim", "enable")

plc_used = source_enabled(config, "plc")
plc_config_path = BASE_DIR /  config.get("plc", "path")

vsp_used = source_enabled(config, "vsp")
vsp_config_path = BASE_DIR /  config.get("vsp", "path")

can_used = source_enabled(config, "can")
can_config_path = BASE_DIR /  config.get("can", "path")

flow_template_dir = BASE_DIR /  config.get("flow", "path")
node_config_path = BASE_DIR /  config.get("node", "path")
bogie_config_path = BASE_DIR /  config.get("bogie", "path")
bed_config_path = BASE_DIR /  config.get("bed", "path")
push_config_path = BASE_DIR /  config.get("push", "path")

db_path = BASE_DIR / config.get("db", "path")
report_template = BASE_DIR / config.get("report", "template")
report_path = BASE_DIR / config.get("report", "path")
theme = config.get("theme","style")
size = (int(config.get("size","w")), int(config.get("size","h")))
# 在 _runtime.py 中添加
print(f"Runtime size: {size}")

bed_data = None
with open(bed_config_path, "r", encoding="utf-8") as f:
    bed_data = json.load(f)

init_runtime(
    base_dir=BASE_DIR,
    config=config,
    sim=sim,
    plc_used=plc_used,
    vsp_used=vsp_used,
    can_used=can_used,
    theme=theme,
    bed_data=bed_data,
    guard = guard,
    size = size,
    paths={
        "plc_config": plc_config_path,
        "vsp_config": vsp_config_path,
        "can_config": can_config_path,
        "flow_dir": flow_template_dir,
        "node_config": node_config_path,
        "bogie_config": bogie_config_path,
        "bed_config" : bed_config_path,
        "report_template": report_template,
        "report_path": report_path,
        "push_config": push_config_path,
        "db": db_path,
    }
)
