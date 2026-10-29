from __future__ import annotations

"""按名称统一解析点位：调用方只给点名，不用理会它属于哪张表。

原来 ui/controls 的三个控件只认 ``runtime["plc"]``，给一个 vsp/can
点名就永远显示 ERR。本模块把三张表串起来：

- 查表顺序固定为 plc -> vsp -> can。当前三张表的点名互不重叠
  （plc 232 点、vsp 14 点、can 4 点，经核对无交集），所以顺序目前
  不影响结果；万一以后出现重名，返回的是排在前面的那张表，并可
  用 :func:`resolve_all` 看到全部命中。
- 三张表的 ``read(name)`` / ``points`` 接口本身已经对齐，直接复用，
  不在这里再造一套读数逻辑。
- 写入只有 plc 支持：vsp 是采集、can 是 SDO 只读，写它们在协议
  层面就不存在。:meth:`ResolvedPoint.write` 对非 plc 点直接抛
  ``TypeError``，控件捕获后按原来的 ERR 路径显示，不会悄悄成功
  也不会崩。
- 点表为 ``None``（app.ini 里该路 enable=false 时 main 不创建表）
  时自动跳过，不报错；三张表全是 None 或点名都不在表里时返回
  ``None``，控件按 ERR 处理，与旧行为一致。
"""

from dataclasses import dataclass
from typing import Any

from _runtime import get_runtime

#: 查表顺序。plc 在前是因为它是唯一可写的路，且控件原本只认它。
SOURCE_ORDER = ("plc", "vsp", "can")

#: 可写路。只有这里的源支持 write()，其余源的点一律只读。
WRITABLE_SOURCES = ("plc",)


@dataclass
class ResolvedPoint:
    """一次按名解析的结果：源名 + 点表 + 点对象。"""

    source: str
    table: Any
    point: Any
    name: str

    @property
    def unit(self) -> str | None:
        """点位单位。三张表的点对象都有 ``unit``（plc 是字段，vsp/can 是属性）。"""
        return getattr(self.point, "unit", None)

    @property
    def is_bool(self) -> bool:
        """是否为 BOOL 点。只有 plc 点有 point_type，且只有 BOOL 算布尔点。

        vsp/can 的点全是数值型（称重、位移、激光），这里返回 False，
        PtLed 因此走数值显示分支，不会把数值误当 ON/OFF。
        """
        return getattr(self.point, "point_type", "") == "BOOL"

    @property
    def writable(self) -> bool:
        return self.source in WRITABLE_SOURCES

    def read(self) -> Any:
        """读当前换算后值（与各表 read(name) 语义一致，None 表示读不到）。"""
        return self.table.read(self.name)

    def write(self, value: Any) -> None:
        """写值。非 plc 点抛 TypeError，调用方按 ERR 处理即可。"""
        if not self.writable:
            raise TypeError(
                f"点位 {self.name!r} 属于只读表 {self.source}，不支持写入"
            )
        self.table.write(self.name, value)


def resolve_all(name: str, runtime: dict[str, Any] | None = None) -> list[ResolvedPoint]:
    """返回点名在三张表里的全部命中（按 SOURCE_ORDER 顺序）。

    通常只有一个命中；返回列表是为了让重名可被发现，而不是被
    默默地按优先级吞掉。
    """
    if runtime is None:
        runtime = get_runtime()
    found: list[ResolvedPoint] = []
    for source in SOURCE_ORDER:
        table = runtime.get(source)
        if table is None:
            continue
        points = getattr(table, "points", None) or {}
        point = points.get(name)
        if point is not None:
            found.append(ResolvedPoint(source, table, point, name))
    return found


def resolve_point(name: str, runtime: dict[str, Any] | None = None) -> ResolvedPoint | None:
    """按名解析点位，找不到返回 None（不抛错，控件按 ERR 显示）。"""
    found = resolve_all(name, runtime)
    return found[0] if found else None


def point_source(name: str, runtime: dict[str, Any] | None = None) -> str | None:
    """只问点名属于哪张表：返回 "plc" / "vsp" / "can"，找不到返回 None。"""
    resolved = resolve_point(name, runtime)
    return resolved.source if resolved is not None else None


def read_point(name: str, runtime: dict[str, Any] | None = None) -> Any:
    """按名读值，找不到返回 None（与各表 read 读不到时的返回值一致）。"""
    resolved = resolve_point(name, runtime)
    return resolved.read() if resolved is not None else None


def write_point(name: str, value: Any, runtime: dict[str, Any] | None = None) -> None:
    """按名写值。找不到点抛 KeyError，非 plc 点抛 TypeError。"""
    resolved = resolve_point(name, runtime)
    if resolved is None:
        raise KeyError(f"点位 {name!r} 不在 plc/vsp/can 三张表里")
    resolved.write(value)


__all__ = [
    "SOURCE_ORDER",
    "WRITABLE_SOURCES",
    "ResolvedPoint",
    "resolve_all",
    "resolve_point",
    "point_source",
    "read_point",
    "write_point",
]
