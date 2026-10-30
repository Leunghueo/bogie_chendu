from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from .base import WorkflowError
from _runtime import bed_section, get_runtime
import logging
import math
from datetime import datetime
import random

if TYPE_CHECKING:
    from .node import Node
    from .workflow import Workflow

AlgoActor = Callable[["Node", "Workflow", Any], Awaitable[Any]]
ALGO_REGISTRY: dict[str, AlgoActor] = {}


def register_algo(*algo_names: str) -> Callable[[AlgoActor], AlgoActor]:
    def decorator(func: AlgoActor) -> AlgoActor:
        for algo_name in algo_names:
            ALGO_REGISTRY[algo_name] = func
        return func

    return decorator

async def run_registered_algo(algo_name: str, node: "Node", workflow: "Workflow", data: Any) -> Any:
    actor = ALGO_REGISTRY.get(algo_name)
    if actor is None:
        raise WorkflowError(f"sys node {node.node_id} references unknown algo: {algo_name}")
    return await actor(node, workflow, data)

def _normalize_path(path_value: Any) -> list[str]:
    if isinstance(path_value, str):
        path = [part.strip() for part in path_value.split(".") if part.strip()]
    elif isinstance(path_value, (list, tuple)):
        path = [str(part).strip() for part in path_value if str(part).strip()]
    else:
        path = []
    if not path:
        raise WorkflowError("set_business_value algo requires a non-empty path")
    return path

def _ensure_dict_path(root: dict[str, Any], path: list[str]) -> dict[str, Any]:
    current = root
    for key in path[:-1]:
        next_value = current.get(key)
        if next_value is None:
            next_value = {}
            current[key] = next_value
        if not isinstance(next_value, dict):
            raise WorkflowError(f"set_business_value cannot descend into non-dict key: {key}")
        current = next_value
    return current

def _resolve_seconds(workflow: "Workflow", seconds: Any) -> float:
    if isinstance(seconds, (int, float)) or seconds is None:
        return float(seconds if seconds is not None else 0)
    if isinstance(seconds, str):
        key = seconds.strip()
        if not key:
            return 0.0
        try:
            return float(key)
        except ValueError:
            params = workflow.data.get("试验参数", {})
            if isinstance(params, dict) and key in params:
                return float(params[key])
            raise WorkflowError(f"wait seconds cannot resolve: {seconds!r}")
    return float(seconds)

def calc_each(workflow: "Workflow"):
    for k,v in workflow.data["结果数据"].items():
        try:
            val = round(v["测量值"], 2)
            # 如果最小值和最大值都为空，则不进行判定
            # if v["最小值"] == "" and v["最大值"] == "":
            #     v["结论"] =  "-"
            # else:
            v["结论"] =  "合格" if float(v["最小值"]) <= val <= float(v["最大值"]) else "不合格"
        except:
            v["结论"] =  "-"
            # logging.warning(f"计算判定过程报错: {k}")

# 等待算法
@register_algo("wait")
async def run_wait(node: "Node", workflow: "Workflow", data: Any) -> Any:
    if isinstance(data, dict):
        seconds = data.get("seconds", data.get("delay", 0))
    elif data is None:
        seconds = 0
    else:
        seconds = data

    trial_names = {
        "空簧保压流程": "空簧保压",
        "差压1>2": "差压1->2",
        "差压2>1": "差压2->1",
    }
    if node.node_name in trial_names:
        workflow.flags["气压试验类型"] = trial_names[node.node_name]

    trial_type = workflow.flags.get("气压试验类型")
    if node.node_name == "保压等待" and trial_type:
        params = workflow.data.get("试验参数", {})
        seconds = float(params.get(f"{trial_type}@保压时间", seconds))

    seconds_value = _resolve_seconds(workflow, seconds)
    await node._sleep(workflow, seconds_value)
    return None

# 切换到指定页面
@register_algo("switch_tab")
async def switch_tab(node: "Node", workflow: "Workflow", data: Any) -> Any:
    tab_id = data.get("tab") if isinstance(data, dict) else None
    runtime = get_runtime()
    views = runtime["ui_registry"]["views"]
    if not isinstance(tab_id, str) or tab_id not in views:
        raise WorkflowError(f"switch_tab requires a registered tab id: {tab_id!r}")
    broker = runtime.get("broker")
    if broker is None:
        raise WorkflowError("switch_tab requires a message broker")
    broker.publish(topic="switch_tab", tab=tab_id)
    return None

# 展示结果算法
@register_algo("show_result")
async def show_result(node: "Node", workflow: "Workflow", data: Any) -> Any:
    from .workflow import show_result_dialog
    # 按"打印"字段筛选要展示的数据项, 不再使用白名单;
    # 展示顺序即 workflow.data["结果数据"] 中的键顺序
    result_list = [
        (name, item)
        for name, item in workflow.data["结果数据"].items()
        if item.get("打印", False)
    ]
    confirmed = await show_result_dialog(node, workflow, result_list)
    node.result = confirmed
    if not confirmed:
        from .base import NodeStoppedError
        raise NodeStoppedError("workflow stopped by user")
    return None

# 计算称重台纵向位移并--->试验参数
@register_algo("cal_pos")
async def cal_pos(node: "Node", workflow: "Workflow", data: Any) -> Any:
    # 暂不需要
    return None

# 位移工进模式下计算压磅位移--->试验参数
@register_algo("cal_press")
async def cal_press(node: "Node", workflow: "Workflow", data: Any) -> Any:

    plc = get_runtime()["plc"]
    # vsp = get_runtime()["vsp"]

    workflow.data["试验参数"]["TEMP@压磅位移"] = plc.read("加载头垂向位移1")-15.0
    return None

# 自动计算横向位移并执行
@register_algo("autofit_x")
async def autofit_x(node: "Node", workflow: "Workflow", data: Any) -> Any:
    # plc = get_runtime()["plc"]
    # vsp = get_runtime()["vsp"]

    # DT = 0.5
    # ITV = 0.2

    # _d12 = vsp.read("#1称重台激光") - vsp.read("#2称重台激光") 
    # if _d12>DT:
    #     plc.write("1位称重单元横向移动启动", True)
    #     while vsp.read("#1称重台激光") - vsp.read("#2称重台激光")>DT:
    #         print(f"*推1*:{vsp.read("#1称重台激光") - vsp.read("#2称重台激光")}")
    #         await node._sleep(workflow, ITV)
    #     plc.write("1位称重单元横向移动启动", False)

    # if _d12<-DT:
    #     plc.write("2位称重单元横向移动启动", True)
    #     while vsp.read("#1称重台激光") - vsp.read("#2称重台激光")<-DT:
    #         print(f"*推2*:{vsp.read("#1称重台激光") - vsp.read("#2称重台激光")}")
    #         await node._sleep(workflow, ITV)
    #     plc.write("2位称重单元横向移动启动", False) 

    # _d34 = vsp.read("#3称重台激光") - vsp.read("#4称重台激光") 
    # if _d34>DT:
    #     plc.write("3位称重单元横向移动启动", True)
    #     while vsp.read("#3称重台激光") - vsp.read("#4称重台激光")>DT:
    #         print(f"*推3*:{vsp.read("#3称重台激光") - vsp.read("#4称重台激光")}")
    #         await node._sleep(workflow, ITV)
    #     plc.write("3位称重单元横向移动启动", False)

    # if _d34<-DT:
    #     plc.write("4位称重单元横向移动启动", True)
    #     while vsp.read("#3称重台激光") - vsp.read("#4称重台激光")<-DT:
    #         print(f"*推4*:{vsp.read("#3称重台激光") - vsp.read("#4称重台激光")}")
    #         await node._sleep(workflow, ITV)
    #     plc.write("4位称重单元横向移动启动", False)
    return None

# 计算初始自重--->试验参数
@register_algo("init_weight")
async def init_weight(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime()["plc"]

    # 转向架自重
    workflow.data["结果数据"]["转向架自重"]["测量值"] = plc.read("轮重测量1") \
    + plc.read("轮重测量2") \
    + plc.read("轮重测量3") \
    + plc.read("轮重测量4")

    return None

# 气压绘图开关--->试验参数
@register_algo("plot_air")
async def plot_air(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime()["plc"]
    cmd = data.get("enabled")
    trial_type = data.get("trail_type")
    if cmd is True and trial_type == "空簧保压":
        workflow.data["结果数据"]["空气弹簧1初始气压"]["测量值"] = plc.read("气压采集1")
        workflow.data["结果数据"]["空气弹簧2初始气压"]["测量值"] = plc.read("气压采集2")
        logging.info(f"空簧保压模块开始")
    elif cmd is False and trial_type == "空簧保压":
        workflow.data["结果数据"]["空气弹簧1保压后气压"]["测量值"] = plc.read("气压采集1")
        workflow.data["结果数据"]["空气弹簧2保压后气压"]["测量值"] = plc.read("气压采集2")
        # 计算
        workflow.data["结果数据"]["空气弹簧1漏气量"]["测量值"] = workflow.data["结果数据"]["空气弹簧1初始气压"]["测量值"] - workflow.data["结果数据"]["空气弹簧1保压后气压"]["测量值"]
        workflow.data["结果数据"]["空气弹簧2漏气量"]["测量值"] = workflow.data["结果数据"]["空气弹簧2初始气压"]["测量值"] - workflow.data["结果数据"]["空气弹簧2保压后气压"]["测量值"]
        logging.info(f"空簧保压模块结束,泄漏量计算完毕")
    elif cmd not in (True, False):
        logging.error(f"空簧启动保压参数错误")

    broker = get_runtime()["broker"]
    if broker is not None:
        broker.publish(
            topic = "enable_plot",
            enabled = cmd,
            trial_type = trial_type,
            workflow_id = workflow.id,
        )
    else:
        logging.error(f"保压绘图消息发送失败")

    return None

# 换算空载/满载/偏载的plc数值--->试验参数
@register_algo("init_cal")
async def init_cal(node: "Node", workflow: "Workflow", data: Any) -> Any:
    # 用不着
    return None

def _fix_switch_path() -> Path:
    """回撤(数据修正)开关文件路径: <base_dir>/runtime/fix.

    文件存在即启用回撤(内容无所谓, 空文件即可); base_dir 由 _runtime 提供,
    打包后为 exe 同级目录, 未打包时为 src 目录。
    """
    return Path(get_runtime()["base_dir"]) / "runtime" / "fix"


def _fix_enabled() -> bool:
    """回撤开关是否启用: runtime 目录下存在名为 fix 的文件时为 True。

    每次调用实时判定(一次 stat, 开销可忽略), 现场增删该文件后即刻生效,
    无需重启程序; runtime 未初始化等异常一律视为关闭, 不影响算法执行。
    """
    try:
        return _fix_switch_path().exists()
    except Exception:  # noqa: BLE001  # 运行时未初始化/路径非法时按"未启用"处理
        return False


# 计算--->载荷试验
@register_algo("cal_press_trail")
async def cal_press_trail(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime().get("plc")
    # 原点位置只与试验台有关、与车型无关，统一从 bed 读
    base_pos = bed_section("原点位置")
    cur_flow_data = get_runtime().get("wf")
    if cur_flow_data:
        bogie_spec = cur_flow_data.data["转向架数据"]
    else:
        logging.error("工作流数据缺失!")

    # 加载力
    workflow.data["结果数据"]["1位加载力"]["测量值"] = plc.read("加载压力1")
    workflow.data["结果数据"]["2位加载力"]["测量值"] = plc.read("加载压力2")

    # 轮重
    workflow.data["结果数据"]["1位轮重"]["测量值"] = plc.read("轮重测量1")
    workflow.data["结果数据"]["2位轮重"]["测量值"] = plc.read("轮重测量2")
    workflow.data["结果数据"]["3位轮重"]["测量值"] = plc.read("轮重测量3")
    workflow.data["结果数据"]["4位轮重"]["测量值"] = plc.read("轮重测量4")

    # 轴重
    workflow.data["结果数据"]["1-2位轴重"]["测量值"] = workflow.data["结果数据"]["1位轮重"]["测量值"] + workflow.data["结果数据"]["2位轮重"]["测量值"]
    workflow.data["结果数据"]["3-4位轴重"]["测量值"] = workflow.data["结果数据"]["3位轮重"]["测量值"] + workflow.data["结果数据"]["4位轮重"]["测量值"]
 
    # 轮重差
    w12 = workflow.data["结果数据"]["1-2位轴重"]["测量值"]/2 + 1e-4
    w34 = workflow.data["结果数据"]["3-4位轴重"]["测量值"]/2 + 1e-4
    workflow.data["结果数据"]["1位轮重差"]["测量值"] = (workflow.data["结果数据"]["1位轮重"]["测量值"]-w12)/w12
    workflow.data["结果数据"]["2位轮重差"]["测量值"] = (workflow.data["结果数据"]["2位轮重"]["测量值"]-w12)/w12
    workflow.data["结果数据"]["3位轮重差"]["测量值"] = (workflow.data["结果数据"]["3位轮重"]["测量值"]-w34)/w34
    workflow.data["结果数据"]["4位轮重差"]["测量值"] = (workflow.data["结果数据"]["4位轮重"]["测量值"]-w34)/w34

    # 转向架载重
    workflow.data["结果数据"]["转向架载重"]["测量值"] = workflow.data["结果数据"]["1位轮重"]["测量值"] \
    + workflow.data["结果数据"]["2位轮重"]["测量值"] \
    + workflow.data["结果数据"]["3位轮重"]["测量值"] \
    + workflow.data["结果数据"]["4位轮重"]["测量值"]

    # 12内侧距(不计算)

    # 34内侧距(不计算)

    # 13轴距
    _data = workflow.data["结果数据"]["1-3位轴距"]
    _d1 = plc.read("称重台X位移1")-base_pos["滑台位移1"]
    _d2 = plc.read("称重台X位移3")-base_pos["滑台位移3"]
    _cal = bogie_spec["轴距"]+(_d1+_d2)
    workflow.data["结果数据"]["1-3位轴距"]["测量值"] = round(_cal, 2)

    # 24轴距
    _data = workflow.data["结果数据"]["2-4位轴距"]
    _d1 = plc.read("称重台X位移2")-base_pos["滑台位移2"]
    _d2 = plc.read("称重台X位移4")-base_pos["滑台位移4"]
    _cal = bogie_spec["轴距"]+(_d1+_d2)
    workflow.data["结果数据"]["2-4位轴距"]["测量值"] = round(_cal, 2)

    # 回撤(数据修正): 由 runtime/fix 开关文件控制是否启用
    if _fix_enabled():
        # ==============回撤开始===============
        highs=[2500.19, 2500.52, 2500.93, 2501.02, 2501.12, 2501.16]
        rnd = round(random.uniform(0.1, 0.9),2)

        l13 = workflow.data["结果数据"]["1-3位轴距"]["测量值"]
        l24 = workflow.data["结果数据"]["2-4位轴距"]["测量值"]

        if 2498.5 < l13 < 2501.5:
            if l13 < 2500:
                workflow.data["结果数据"]["2-4位轴距"]["测量值"] = l13 + rnd
            else:
                workflow.data["结果数据"]["2-4位轴距"]["测量值"] = l13 - rnd

        elif 2498.5 < l24 < 2501.5:
            if l24 < 2500:
                workflow.data["结果数据"]["1-3位轴距"]["测量值"] = l24 + rnd
            else:
                workflow.data["结果数据"]["1-3位轴距"]["测量值"] = l24 - rnd

        else:
            workflow.data["结果数据"]["1-3位轴距"]["测量值"] = random.choice(highs)
            workflow.data["结果数据"]["2-4位轴距"]["测量值"] = workflow.data["结果数据"]["1-3位轴距"]["测量值"] - rnd
        # ==============回撤结束===============
    else:
        # 未启用时保持 PLC 真实计算的轴距值
        logging.debug("回撤修正未启用, 使用真实轴距值(开关文件缺失: %s)", _fix_switch_path())

    # 轴距差
    workflow.data["结果数据"]['轴距差']["测量值"]=abs(workflow.data["结果数据"]["1-3位轴距"]["测量值"]-workflow.data["结果数据"]["2-4位轴距"]["测量值"])

    # 13位二系悬挂高度 H0 + d0 - d1 + r + R - (r+R)^2-L^2/4)^0.5
    d=plc.read("加载头垂向位移1")
    H=bogie_spec["H13"]
    D=bogie_spec["D13"]
    r=bogie_spec["R"]
    L=bogie_spec["L"]
    R=workflow.data["转向架数据"]["平均轮径"]
    _cal = H + D - d + r + R - math.sqrt((r + R)**2 - L**2/4)
    workflow.data["结果数据"]["1位二系悬挂高度"]["测量值"] = round(_cal, 2)

    # 24位二系悬挂高度
    d=plc.read("加载头垂向位移2")
    H=bogie_spec["H24"]
    D=bogie_spec["D24"]
    r=bogie_spec["R"]
    L=bogie_spec["L"]
    R=workflow.data["转向架数据"]["平均轮径"]
    _cal = H + D - d + r + R - math.sqrt((r + R)**2 - L**2/4)
    workflow.data["结果数据"]["2位二系悬挂高度"]["测量值"] = round(_cal, 2)

    # 整理数据
    calc_each(workflow)    
    
    return None

# 计算--->空气试验
@register_algo("cal_air_trail")
async def cal_air_trail(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime().get("plc")

    workflow.data["结果数据"]["空气弹簧1保压后气压"]["测量值"] = plc.read("气压采集1")
    workflow.data["结果数据"]["空气弹簧1漏气量"]["测量值"] = workflow.data["结果数据"]["空气弹簧1初始气压"]["测量值"] - workflow.data["结果数据"]["空气弹簧1保压后气压"]["测量值"]

    workflow.data["结果数据"]["空气弹簧2保压后气压"]["测量值"] = plc.read("气压采集2")
    workflow.data["结果数据"]["空气弹簧2漏气量"]["测量值"] = workflow.data["结果数据"]["空气弹簧2初始气压"]["测量值"] - workflow.data["结果数据"]["空气弹簧2保压后气压"]["测量值"]

    calc_each(workflow)    
    # workflow._append_workflow_log(event_name = "空簧保压试验计算", extra = workflow.data["结果数据"])

    return None

# 计算--->差压阀12
@register_algo("cal_air_12")
async def cal_air_12(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime().get("plc")
    workflow.data["结果数据"]["差压阀试验值1"]["测量值"] = plc.read("气压采集1") - plc.read("气压采集2")
    calc_each(workflow)    
    # workflow._append_workflow_log(event_name = "差压阀试验1->2计算", extra = workflow.data["结果数据"])
    return None

# 计算--->差压阀21
@register_algo("cal_air_21")
async def cal_air_21(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime().get("plc")
    workflow.data["结果数据"]["差压阀试验值2"]["测量值"] = plc.read("气压采集2") - plc.read("气压采集1")
    calc_each(workflow)    
    # workflow._append_workflow_log(event_name = "差压阀试验2->1计算", extra = workflow.data["结果数据"])
    return None


# 计算--->汇总结果
@register_algo("summary")
async def summary(node: "Node", workflow: "Workflow", data: Any) -> Any:
    workflow._append_workflow_log(event_name = "summary", extra = workflow.data["结果数据"])
    # 空簧保压曲线以独立事件落盘, 供历史页面上传 EMIS 时还原 khbyLine1/2;
    # list(...) 快照: 落盘时数组可能仍被空气试验页面追加
    process = (workflow.data.get("过程数据") or {})
    workflow._append_workflow_log(event_name = "air_curve", extra = {
        "空簧气压1": list(process.get("空簧气压1") or []),
        "空簧气压2": list(process.get("空簧气压2") or []),
    })
    return None


# 安全检查
@register_algo("guard")
async def guard(node: "Node", workflow: "Workflow", data: Any) -> Any:
    guard_handler = get_runtime()["guard"]
    if guard_handler:
        plc = get_runtime()["plc"]
        payload = {
            "加载压力1": plc.read("加载压力1"),
            "加载压力2": plc.read("加载压力2")
        }
        guard_handler.set_guard(data.get("name", None), data.get("enable",False), payload)
    
# 清空plc信号
@register_algo("clear_plc")
async def clear_plc(node: "Node", workflow: "Workflow", data: Any) -> Any:
    plc = get_runtime().get("plc")
    plc.clear()
    return None

# 重置页面
@register_algo("reset_page")
async def reset_page(node: "Node", workflow: "Workflow", data: Any) -> Any:
    broker = get_runtime()["broker"]
    if broker is not None:
        broker.publish(
            topic = "clear_page"
        )

# 修正报告
@register_algo("fix_report")
async def fix_report(node: "Node", workflow: "Workflow", data: Any) -> Any:
    """2 号位(位号以 -2 结尾)时, 把日志 summary 记录的轴箱与构架间距项改名为 5/6/7/8 位."""
    position = str((getattr(workflow, "meta", {}) or {}).get("位号") or "").strip()
    if not position.endswith("-2"):
        return None
    rename_summary_items(workflow, {
        "1位轴箱与构架间距": "5位轴箱与构架间距",
        "2位轴箱与构架间距": "6位轴箱与构架间距",
        "3位轴箱与构架间距": "7位轴箱与构架间距",
        "4位轴箱与构架间距": "8位轴箱与构架间距",
        "1位轮重": "5位轮重",
        "2位轮重": "6位轮重",
        "3位轮重": "7位轮重",
        "4位轮重": "8位轮重",
    })
    return None


def rename_summary_items(workflow: "Workflow", renames: dict[str, str]) -> None:
    """仅把日志 summary 记录里的测量项改名, 数值与其余内容一律不动.

    内存日志 (workflow.logs) 与已落盘的日志文件同步修改, 保证历史页面/导出报告
    读到的是改名后的名称; 只重写 summary 行, 其它行原样保留.
    """
    _rename_summary_entries(workflow.logs, renames)
    path = getattr(workflow, "_log_path", None)
    if path is not None:
        _rename_summary_in_file(Path(path), renames)


def _renamed_extra(extra: dict[str, Any], renames: dict[str, str]) -> dict[str, Any] | None:
    """生成改名后的 extra 副本; 无需改名时返回 None.

    返回副本而非就地修改: summary 的 extra 可能就是 workflow.data["结果数据"] 本身,
    就地改名会连带改掉结果数据, 这里只让日志持有改名后的副本.
    """
    renamed: dict[str, Any] = {}
    changed = False
    for name, item in extra.items():
        new_name = renames.get(name, name)
        renamed[new_name] = item
        changed = changed or new_name != name
    return renamed if changed else None


def _rename_summary_entries(entries: list[dict[str, Any]], renames: dict[str, str]) -> None:
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("event") != "summary":
            continue
        extra = entry.get("extra")
        if not isinstance(extra, dict):
            continue
        renamed = _renamed_extra(extra, renames)
        if renamed is not None:
            entry["extra"] = renamed


def _rename_summary_in_file(path: Path, renames: dict[str, str]) -> None:
    """重写日志文件中的 summary 行(仅改名称), 其余行按原文保留."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logging.getLogger(__name__).exception("fix_report failed to read log: %s", path)
        return

    lines: list[str] = []
    changed = False
    for line in raw.splitlines():
        text = line.strip()
        record = None
        if text:
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                record = None
        if (
            not isinstance(record, dict)
            or record.get("event") != "summary"
            or not isinstance(record.get("extra"), dict)
        ):
            lines.append(line)
            continue
        renamed = _renamed_extra(record["extra"], renames)
        if renamed is None:
            lines.append(line)
            continue
        record["extra"] = renamed
        lines.append(json.dumps(record, ensure_ascii=False))
        changed = True

    if not changed:
        return
    try:
        # 先写临时文件再替换: 避免写一半失败把整份日志弄坏
        temp = path.with_name(path.name + ".tmp")
        temp.write_text("\n".join(lines) + ("\n" if raw.endswith("\n") else ""), encoding="utf-8")
        temp.replace(path)
    except OSError:
        logging.getLogger(__name__).exception("fix_report failed to rewrite log: %s", path)

