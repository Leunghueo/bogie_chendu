"""EMIS 上报模块: POST+XML 形式构造报文并上报.

字段填充规则详见 src/docs/upload.md 中的 emis 替换逻辑对照表.

注: iot 相关代码已迁移至 `libs.push.iot`; 共享基础 (异常类 / config 加载 / runtime
访问器) 见 `libs.push._base`.
"""

from __future__ import annotations

import base64
import copy
import logging
import re
import struct
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
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


class EmisResultError(PushError):
    """EMIS 接口返回了非 S_ACCEPTED 的统一结果码."""


# EMIS 接口统一返回结果 (对接文档 表4)
_EMIS_ACCEPTED = "S_ACCEPTED"
_EMIS_RESULT_HINTS: dict[str, str] = {
    "S_ACCEPTED": "上传成功",
    "S_REFUSED": "调用成功,但数据被拒绝",
    "S_INVALIDDEVICE": "调用成功, 无效或未知的设备",
    "S_INVALIDTYPE": "调用成功, 无效或未知的数据类型",
    "S_INVALIDDATA": "调用成功, 无效的接口数据(校验失败)",
    "S_UNKNOWNERROR": "调用成功, 未知错误",
}
# 从响应体中提取返回码 (兼容纯文本 / result=S_XXX / {"result":"S_XXX"} 等形式)
_EMIS_RESULT_RE = re.compile(r"\bS_[A-Z]+\b")


# ---------------------------------------------------------------------- #
# 通用工具 (EMIS 专用)
# ---------------------------------------------------------------------- #


def _to_xml(data: dict, root_tag: str) -> str:
    """递归把 dict 序列化为 XML 字符串, 根节点为 root_tag.

    若 data 是单 key 字典且 key 等于 root_tag, 则用 value 作为根内容.
    """
    if isinstance(data, dict) and len(data) == 1 and root_tag in data:
        data = data[root_tag]
    root = ET.Element(root_tag)
    _populate_element(root, data)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
        root, encoding="unicode", short_empty_elements=True
    )


def _populate_element(parent: ET.Element, value: Any) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            child = ET.SubElement(parent, k)
            _populate_element(child, v)
    elif isinstance(value, list):
        for item in value:
            child = ET.SubElement(parent, "item")
            _populate_element(child, item)
    elif value is None:
        parent.text = ""
    else:
        parent.text = str(value)


def _format_dt(stime: str | None) -> str:
    """将 Node.stime/etime (yy-MM-dd HH:MM:SS) 重格式化为 yyyy-MM-dd hh:mm:ss.

    若 stime 为空或解析失败, 返回当前时间.
    """
    if stime:
        try:
            return datetime.strptime(stime, "%y-%m-%d %H:%M:%S").strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            pass
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _get_result_data(wf: Any) -> dict:
    if wf is None:
        return {}
    return (getattr(wf, "data", {}) or {}).get("结果数据", {}) or {}


def _get_air_curves(wf: Any) -> dict:
    """从 workflow.data["过程数据"] 取空簧气压曲线数组, e.g. {"空簧气压1": [...], ...}."""
    if wf is None:
        return {}
    process = (getattr(wf, "data", {}) or {}).get("过程数据", {}) or {}
    return {key: process.get(key) for key in ("空簧气压1", "空簧气压2") if key in process}


def _air2b64(values: Any) -> str:
    """气压数组 -> C# 兼容的 float32 小端 base64 字符串.

    布局与原 C# LineData (dataUpload.cs) 一致:
      前 N 个浮点数 = 时间(分钟, 第 i 点 = i 秒 / 60),
      后 N 个 = 气压值;
    空数据/非法元素返回 "" (与 C# catch-all 返回 "" 行为一致).
    """
    if not isinstance(values, (list, tuple)) or not values:
        return ""
    try:
        n = len(values)
        floats = [i / 60.0 for i in range(n)] + [float(v) for v in values]
        return base64.b64encode(struct.pack(f"<{2 * n}f", *floats)).decode("ascii")
    except (TypeError, ValueError, struct.error):
        return ""


def _get_current_user() -> str:
    return str(get_runtime().get("current_user") or "")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------- #
# EMIS 上报
# ---------------------------------------------------------------------- #


def _build_emis_payload(
    summary: dict,
    meta: dict,
    bed: dict,
    cfg: dict,
    check_start: str,
    check_end: str,
    air_curves: dict | None = None,
) -> dict:
    """构造 emis 要 POST 的 param, 包含 Data XML 字符串.

    直接使用 summary + meta + bed 构造 payload, 不依赖 workflow.
    air_curves: 空簧气压曲线数组 {"空簧气压1": [...], "空簧气压2": [...]}, 编码进 khbyLine1/2.
    """
    emis_cfg = cfg.get("emis", {})
    data_demo = copy.deepcopy(emis_cfg.get("data_demo", {}))
    cr = data_demo.setdefault("CheckRecord", {})

    device_code = bed.get("设备编号", "")
    user = _get_current_user()

    # BasicInfo
    basic = cr.setdefault("BasicInfo", {})
    basic["Version"] = "1.0"
    basic["DeviceCode"] = device_code
    basic["FactoryID"] = "10002"
    basic["GernerateTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # StuffInfo
    stuff = cr.setdefault("StuffInfo", {})
    stuff["OperatorID"] = ""
    stuff["OperatrName"] = user

    # DeviceInfo
    dev = cr.setdefault("DeviceInfo", {})
    dev["ZhouHao"] = ""
    dev["CheHao"] = str(meta.get("位号", ""))
    dev["ZhuanXiangJiaBianHao"] = str(meta.get("编号", ""))
    dev["IDNO"] = ""
    dev["CheckStartTime"] = check_start
    dev["CheckEndTime"] = check_end

    # CheckData
    cd = cr.setdefault("CheckData", {})
    cd["BG_type"] = f"{meta.get('车型', '')}{meta.get('编号', '')}"
    cd["BogieNo"] = str(meta.get("编号", ""))
    cd["BG_Direction"] = "0"
    cd["User"] = user
    cd["wheelset_Front"] = ""
    cd["wheelset_Rear"] = ""
    cd["No_of_the_beam_of_the_springs"] = ""
    cd["No_of_tilting_beam"] = device_code
    cd["distance_run"] = ""
    cd["Building_year"] = ""
    cd["Type_of_maintenance"] = ""
    cd["No_of_vehicle"] = str(meta.get("车号", ""))
    cd["Gauge_of_the_track"] = "1435"
    cd["Wheel_diameter"] = ""
    # 空簧保压曲线: 编码为 C# 兼容的 base64 (前半时间-分钟, 后半气压值)
    curves = air_curves or {}
    cd["khbyLine1"] = _air2b64(curves.get("空簧气压1"))
    cd["khbyLine2"] = _air2b64(curves.get("空簧气压2"))

    # 转向架自重
    tare_item = summary.get("转向架自重") or {}
    tare_val = tare_item.get("测量值", "")
    cd["Net_Weight"] = _fmt_number(tare_val)
    cd["Tare"] = tare_val
    cd["Gross"] = tare_val

    # Max_load = 1位加载力 + 2位加载力
    p1 = _safe_float((summary.get("1位加载力") or {}).get("测量值", 0))
    p2 = _safe_float((summary.get("2位加载力") or {}).get("测量值", 0))
    cd["Max_load"] = round(p1 + p2, 3)

    cd["Lateral_force"] = ""
    cd["Air_pressure"] = (summary.get("空气弹簧1初始气压") or {}).get("测量值", "")
    cd["Wheel_base_AC"] = ""
    cd["Wheel_base_CE"] = ""
    cd["Height_of_wheelflange"] = ""
    cd["Crossbar_to_top_of_rail"] = ""

    # measureResultList: 遍历 summary, 按 1-based 序号
    measure_list = []
    for idx, (name, item) in enumerate(summary.items(), start=1):
        if not isinstance(item, dict):
            continue
        measure_list.append({
            "No": str(idx),
            "Label": name,
            "Description": "",
            "Minimum": item.get("最小值", "-"),
            "Current": item.get("测量值", "-"),
            "Maximum": item.get("最大值", "-"),
            "Unit": item.get("单位", "-"),
            "Decision": item.get("结论", "-"),
        })
    cd["measureResultList"] = measure_list

    # 序列化 XML
    xml_str = _to_xml(data_demo, root_tag="CheckRecord")

    # 构造最终 param
    param = {
        "DeviceType": "BGSL",
        "DeviceID": device_code,
        "DataType": "DEVICEDATA",
        "Data": xml_str,
    }
    return {"url": emis_cfg.get("url", ""), "param": param}


def _fmt_number(v: Any) -> str:
    if v is None or v == "":
        return ""
    try:
        return str(round(float(v), 3))
    except (TypeError, ValueError):
        return str(v)


def emis(
    summary: dict | None = None,
    meta: dict | None = None,
    check_start: str | None = None,
    check_end: str | None = None,
    air_curves: dict | None = None,
) -> bool:
    """数据上报 EMIS: 构造 XML 报文并 POST 到 config.url.

    支持两种调用方式:
    1. 直接传 summary + meta + check_start + check_end: 用于历史日志等
       没有活动 workflow 的场景, 数据完全来自调用方;
    2. 不传任何参数: 从 runtime["wf"] 自动取 (运行中的工作流).

    Args:
        summary: 结果数据字典, e.g. {"1位加载力": {"测量值": ...}, ...}.
        meta: 工作流元信息, e.g. {"车型": ..., "编号": ..., "车号": ..., "位号": ...}.
        check_start: 试验开始时间, 格式 "yyyy-MM-dd HH:MM:SS".
        check_end: 试验结束时间, 格式同上.
        air_curves: 空簧气压曲线 {"空簧气压1": [...], "空簧气压2": [...]},
            编码为 base64 填入 khbyLine1/2; 缺省回落 runtime wf 的过程数据.

    Returns:
        True 成功; 失败抛 PushError (RuntimeError 子类), 错误详情同时写入当天日志.

    Raises:
        PushConfigError: 配置文件读取/解析失败, 或缺少 emis.url.
        EmisResultError: EMIS 返回非 S_ACCEPTED 的结果码.
        RuntimeError: 报文构造失败 / 网络连接失败.
    """
    # 配置读取失败单独报错, 不再笼统归入"上报失败" (错误详情已由 _load_push_config 写入当天日志)
    cfg = _load_push_config()
    bed = _get_bed()

    # 缺省时回落到 runtime["wf"]
    wf = None
    if (
        summary is None
        or meta is None
        or check_start is None
        or check_end is None
        or air_curves is None
    ):
        wf = _get_workflow()
    if summary is None:
        summary = _get_result_data(wf)
    if meta is None:
        meta = _get_meta(wf)
    if air_curves is None:
        air_curves = _get_air_curves(wf)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if check_start is None:
        if wf is not None:
            head = wf.nodes.get("head")
            check_start = (
                _format_dt(getattr(head, "stime", None))
                if head is not None
                else now_str
            )
        else:
            check_start = now_str
    if check_end is None:
        if wf is not None:
            end = wf.nodes.get("end")
            check_end = (
                _format_dt(getattr(end, "etime", None))
                if end is not None
                else now_str
            )
        else:
            check_end = now_str

    try:
        built = _build_emis_payload(summary, meta, bed, cfg, check_start, check_end, air_curves)
    except Exception as exc:  # noqa: BLE001
        msg = f"EMIS 报文构造失败: {exc}"
        logger.exception(msg)
        raise RuntimeError(msg) from exc

    url = built["url"]
    if not url:
        msg = f"推送配置缺少 emis.url, 无法上报 EMIS: {_push_config_path()}"
        logger.error(msg)
        raise PushConfigError(msg)

    form_body = urllib.parse.urlencode(built["param"]).encode("utf-8")
    req = urllib.request.Request(url, data=form_body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        msg = f"EMIS 上报失败: 服务返回 HTTP {exc.code} {exc.reason} (url={url})"
        logger.exception(msg)
        raise RuntimeError(msg) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        msg = f"EMIS 上报失败: 无法连接 {url} ({reason})"
        logger.exception(msg)
        raise RuntimeError(msg) from exc
    except OSError as exc:
        msg = f"EMIS 上报失败: 网络异常 {exc} (url={url})"
        logger.exception(msg)
        raise RuntimeError(msg) from exc

    logger.info("EMIS 响应: status=%s body=%s", status, body[:200])

    # 校验统一返回结果码 (表4)
    match = _EMIS_RESULT_RE.search(body)
    result_code = match.group(0) if match else ""
    if result_code == _EMIS_ACCEPTED:
        logger.info("EMIS 上报成功: %s", result_code)
        return True
    if result_code:
        hint = _EMIS_RESULT_HINTS.get(result_code, "未知返回码")
        msg = f"EMIS 返回 {result_code}: {hint}"
        logger.error(msg)
        raise EmisResultError(msg)
    msg = f"EMIS 返回内容无法识别(非标准返回码): {body[:100]!r}"
    logger.error(msg)
    raise EmisResultError(msg)


# ---------------------------------------------------------------------- #
# CAA 暂不实现
# ---------------------------------------------------------------------- #


def cca() -> None:
    """暂不实现, 保持空函数占位."""
    pass
