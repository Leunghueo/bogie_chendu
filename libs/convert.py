from __future__ import annotations

"""公共原始值换算：plc / vsp / can 三路共用。

约定（与原 plc/vsp 实现一致，不改现场标定语义）：
- 读方向：真值 = segs.apply(原始值) + add
- 写方向（仅 plc INT 沿用）：原始值 = segs.apply_reverse(真值) + add
  注意这不是读方向的严格数学逆函数（严格逆应为
  apply_reverse(真值 - add)），但原 plc 写路径就是这样跑的，
  现场标定也是按这个路径对出来的，所以这里原样保留，不擅自“纠正”。
- BOOL 不走本换算：plc 的 BOOL 直接返回原始布尔值。
"""

from dataclasses import dataclass

try:
    from segs import SegmentMapping
except ModuleNotFoundError:  # pragma: no cover - fallback for package imports
    from main.libs.segs import SegmentMapping


@dataclass(frozen=True)
class RawValueConverter:
    """一段 segs 分段曲线 + 一个 add 偏移的换算器。"""

    segs: SegmentMapping
    add: float = 0.0

    def to_true(self, raw_value: float | int | None, *, round_digits: int | None = None) -> float | None:
        """原始值 -> 真值。raw_value 为 None 时返回 None，不抛错。"""
        if raw_value is None:
            return None
        value = self.segs.apply(float(raw_value)) + self.add
        if round_digits is not None:
            value = round(value, round_digits)
        return value

    def to_raw(self, true_value: float | int) -> float:
        """真值 -> 原始值（沿用原 plc 写路径：先反向查表，再加 add）。"""
        return self.segs.apply_reverse(float(true_value)) + self.add


def convert_raw_value(
    raw_value: float | int | None,
    segs: SegmentMapping,
    add: float = 0.0,
    *,
    round_digits: int | None = None,
) -> float | None:
    """函数式入口：不需要持有换算器对象时直接用。"""
    return RawValueConverter(segs=segs, add=add).to_true(raw_value, round_digits=round_digits)
