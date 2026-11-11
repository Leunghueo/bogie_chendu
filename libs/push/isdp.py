"""ISDP 数据上传模块: POST + JSON 形式构造报文并上传到设备数据接口.

接口: POST http://10.194.96.177:8000/api/v3/equipmentData
      Content-Type: application/json; charset=UTF-8
应答: JSON, resCode == "0" 表示接口调用成功, resMsg 为结果说明,
      reqId 供全链路追踪.

字段来源 (与需求对照):
  OnlineToken <- push config.json 的 isdp.token
                 (路径: app.ini [push] path -> config 文件 -> isdp -> token)
  DeviceCode  <- bed.json 设备编号;  BasicInfo.DeviceName <- bed.json 设备名称
  CheckData   <- 作业 summary (结果数据) 的测量值, 键名映射见 _CHECK_FIELD_MAP;
                 外层键为任务编号 (作业名)
  BasicInfo   <- 作业 meta / 作业行: 车型、车号、架位号 (编号-位号)、
                 试验结束时间 (finished_at)、操作员 (作业 user)

与 emis.py 共用 libs.push._base 的配置加载与异常类; 本模块只负责 ISDP
协议本身, 不依赖运行中的 workflow (历史页按作业库行调用).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from _runtime import get_runtime

from ._base import (
    PushConfigError,
    PushError,
    _get_bed,
    _get_meta,
    _get_workflow,
    _load_push_config,
    _push_config_path,
)

logger = logging.getLogger(__name__)

# 接口地址: 需求给定; config.isdp.url 存在且非空时以 config 为准 (便于现场改址)
ISDP_URL = "http://10.194.96.177:8000/api/v3/equipmentData"
_TIMEOUT_SECONDS = 10


class IsdpResultError(PushError):
    """ISDP 接口返回了非 0 的 resCode, 或应答无法解析."""


# CheckData 字段映射: ISDP 键 <- summary (结果数据) 的条目名, 取其 "测量值".
# 需求样例中 "CYFXLL2" 出现两次 (第二次备注为空簧保压泄漏量2), 与 BYXLL2 重复,
# 按字段命名规律取: BYXL = 空簧保压漏气量, CYFXL = 差压阀试验值.
# ZJCC 的备注为 "轴距13/轴距24", 结果数据中对应的实测条目是 1-3位轴距 / 2-4位轴距.
_CHECK_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("BYXLL1", "空气弹簧1漏气量"),
    ("BYXLL2", "空气弹簧2漏气量"),
    ("CYFXLL1", "差压阀试验值1"),
    ("CYFXLL2", "差压阀试验值2"),
    ("ZJCC1", "1-3位轴距"),
    ("ZJCC2", "2-4位轴距"),
    ("ZXJGJX1", "1位轴箱与构架间距"),
    ("ZXJGJX2", "2位轴箱与构架间距"),
    ("ZXJGJX3", "3位轴箱与构架间距"),
    ("ZXJGJX4", "4位轴箱与构架间距"),
    ("LZJGDC1", "联轴节高度差1"),
    ("LZJGDC2", "联轴节高度差2"),
)


def _measure(summary: dict, name: str) -> Any:
    """取 summary 条目的 "测量值"; 条目缺失或结构异常时返回 "" (不中断整包上传)."""
    item = summary.get(name)
    if isinstance(item, dict):
        value = item.get("测量值", "")
        return "" if value is None else value
    return ""


def _frame_no(meta: dict) -> str:
    """架位号 = 编号 (架号) - 位号; 任一缺失时用现有的那一个."""
    parts = [str(meta.get(key) or "").strip() for key in ("编号", "位号")]
    return "-".join(part for part in parts if part)


def _build_isdp_payload(
    summary: dict,
    meta: dict,
    bed: dict,
    cfg: dict,
    *,
    task_no: str,
    check_end: str,
    operator: str,
) -> dict:
    """构造 ISDP 要 POST 的 JSON 报文 (纯数据组装, 不做网络请求)."""
    isdp_cfg = cfg.get("isdp") or {}
    token = str(isdp_cfg.get("token") or "").strip()
    if not token:
        msg = f"推送配置缺少 isdp.token, 无法上传 ISDP: {_push_config_path()}"
        logger.error(msg)
        raise PushConfigError(msg)

    frame_no = _frame_no(meta)
    check_data = {
        field: _measure(summary, source) for field, source in _CHECK_FIELD_MAP
    }
    return {
        "OnlineToken": token,
        "DeviceCode": str(bed.get("设备编号", "") or ""),
        "DataType": "DEVICEDATA",
        "CheckData": {task_no: check_data},
        "BasicInfo": {
            "DeviceName": str(bed.get("设备名称", "") or ""),
            "CheckTime": check_end,
            "TrnsetType": str(meta.get("车型", "") or ""),
            "TrnsetNo": str(meta.get("车号", "") or ""),
            "TrnsetTrainNo": frame_no,
            "PositionNo": frame_no,
            "SerialNum": "",
            "OperatorName": operator,
            "OperatorID": "",
            "Remark": "",
        },
    }


def _isdp_url(cfg: dict) -> str:
    url = str((cfg.get("isdp") or {}).get("url") or "").strip()
    return url or ISDP_URL


def isdp(
    summary: dict | None = None,
    meta: dict | None = None,
    *,
    task_no: str = "",
    check_end: str | None = None,
    operator: str | None = None,
) -> dict:
    """数据上传 ISDP: 构造 JSON 报文并 POST 到设备数据接口.

    调用方式与 emis 对齐:
    1. 显式传 summary + meta + task_no + check_end + operator: 历史页按
       作业库行调用, 数据完全来自调用方;
    2. 缺省参数回落 runtime["wf"] (运行中的工作流) 与当前登录用户.

    Args:
        summary: 结果数据字典, e.g. {"空气弹簧1漏气量": {"测量值": ...}, ...}.
        meta: 作业元信息, e.g. {"车型": ..., "车号": ..., "编号": ..., "位号": ...}.
        task_no: 任务编号, 作为 CheckData 的外层键; 缺省用工作流名.
        check_end: 试验结束时间字符串, 作为 BasicInfo.CheckTime.
        operator: 操作员姓名 (BasicInfo.OperatorName).

    Returns:
        接口应答 dict (resCode == "0" 时); 失败抛 PushError 子类,
        错误详情同时写入当天日志.

    Raises:
        PushConfigError: 配置文件读取/解析失败, 或缺少 isdp.token.
        IsdpResultError: ISDP 返回非 0 的 resCode, 或应答不是预期 JSON.
        RuntimeError: 报文构造失败 / 网络连接失败.
    """
    cfg = _load_push_config()
    bed = _get_bed()

    wf = None
    if summary is None or meta is None:
        wf = _get_workflow()
    if summary is None:
        data = getattr(wf, "data", {}) or {}
        summary = data.get("结果数据", {}) or {}
    if meta is None:
        meta = _get_meta(wf)
    if not task_no:
        task_no = str(getattr(wf, "name", "") or "") if wf is not None else ""
    if check_end is None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if wf is not None:
            end = (getattr(wf, "nodes", {}) or {}).get("end")
            etime = getattr(end, "etime", None) if end is not None else None
            check_end = str(etime) if etime else now_str
        else:
            check_end = now_str
    if operator is None:
        operator = str(get_runtime().get("current_user") or "")

    try:
        payload = _build_isdp_payload(
            summary,
            meta,
            bed,
            cfg,
            task_no=task_no,
            check_end=str(check_end),
            operator=str(operator),
        )
    except PushError:
        raise
    except Exception as exc:  # noqa: BLE001
        msg = f"ISDP 报文构造失败: {exc}"
        logger.exception(msg)
        raise RuntimeError(msg) from exc

    url = _isdp_url(cfg)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json; charset=UTF-8")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            status = resp.status
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        msg = f"ISDP 上传失败: 服务返回 HTTP {exc.code} {exc.reason} (url={url})"
        logger.exception(msg)
        raise RuntimeError(msg) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        msg = f"ISDP 上传失败: 无法连接 {url} ({reason})"
        logger.exception(msg)
        raise RuntimeError(msg) from exc
    except OSError as exc:
        msg = f"ISDP 上传失败: 网络异常 {exc} (url={url})"
        logger.exception(msg)
        raise RuntimeError(msg) from exc

    logger.info("ISDP 响应: status=%s body=%s", status, text[:200])
    try:
        result = json.loads(text)
    except ValueError:
        result = None
    if not isinstance(result, dict) or "resCode" not in result:
        msg = f"ISDP 返回内容无法识别(非预期 JSON 应答): {text[:100]!r}"
        logger.error(msg)
        raise IsdpResultError(msg)
    if str(result.get("resCode")) == "0":
        logger.info(
            "ISDP 上传成功: resMsg=%s reqId=%s",
            result.get("resMsg", ""),
            result.get("reqId", ""),
        )
        return result
    msg = (
        f"ISDP 返回 resCode={result.get('resCode')}: "
        f"{result.get('resMsg', '')} (reqId={result.get('reqId', '')})"
    )
    logger.error(msg)
    raise IsdpResultError(msg)
