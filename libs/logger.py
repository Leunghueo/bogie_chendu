from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

LOGPATH = ""
LOG_SYS = ""


def configure_application_logging(base_dir: str | Path | None = None) -> Path:
    """配置全局日志: stderr + logs/daily/<启动日期>.log, 级别 INFO.

    作业 (流程) 日志不在此列: 它随作业记录存入 bogie.db 的
    TblFlowJob.logs 列 (见 libs/wf/workflow.py 与 libs/jobstore.py).
    """
    global LOGPATH, LOG_SYS

    LOGPATH = base_dir
    LOG_SYS = LOGPATH / "logs/daily"
    LOG_SYS.mkdir(parents=True, exist_ok=True)

    syslog = LOG_SYS / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    root_logger = logging.getLogger()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(syslog, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return syslog
