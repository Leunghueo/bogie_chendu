from __future__ import annotations

"""CAN 点表：SocketCAN + CANopen SDO 只读采集。

与 demo.py 的关系（刻意保持一致，demo 是已验证过的逻辑）：
- SDO 协议原样照搬 demo：expedited upload，请求帧首字节 0x40，
  发送 ID 0x600+节点号，接收 ID 0x580+节点号；忽略无关帧；
  0x80 为 abort；应答首字节 0x4F/0x4B/0x47/0x43 分别对应 1/2/3/4 字节，
  数据小端解析；超时、abort、非法分辨率都按 demo 的方式抛错/标记。
- 每个点依次读三项：位置、分辨率、报警；位置换算为
  position_mm = 有符号原始值 * 分辨率(nm) / 1_000_000，
  然后再走公共换算（segs.apply 后 +add），与 plc/vsp 同一套。
- 报警对象字典里没有给：沿用 demo 的 0x6503:00。

与 demo.py 的不同（为了能进主程序的点表体系）：
- demo 是 python-can + 独立命令行；这里不用 python-can，原因有二：
  1) 本包就叫 can，libs 在 sys.path 上时 `import can` 会先命中
     libs/can 自身，拿不到 python-can 的 Bus；
  2) 当前环境也没有装 python-can。
  因此用标准库 socket 的 AF_CAN/SOCK_RAW 直接收发 CAN 帧，
  SDO 帧字节与 demo 完全一致，现场验证结论仍然适用。
- 点位来自 can.json（config + pts），不再写死节点号和对象字典；
  轮询线程、broker 事件、snapshot/describe/update_by_id/reload
  的形态与 plc/vsp 对齐，便于后续 UI 统一显示。
- 超时和轮询间隔以 can.json 的 config 为准（sdo_timeout_ms、
  poll_interval_ms），不再用 demo 里写死的 0.20s / 0.10s。
"""

import json
import logging
import socket
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from segs import SegmentMapping
except ModuleNotFoundError:  # pragma: no cover - fallback for package imports
    from main.libs.segs import SegmentMapping

try:
    from convert import RawValueConverter
except ModuleNotFoundError:  # pragma: no cover - fallback for package imports
    from main.libs.convert import RawValueConverter

logger = logging.getLogger(__name__)

# demo.py 的默认值：can.json 的 dict 里没有报警对象时用它。
ALARM_INDEX = 0x6503
ALARM_SUBINDEX = 0x00

# demo.py 应答首字节 -> 数据字节数（expedited upload）。
_SDO_SIZES = {0x4F: 1, 0x4B: 2, 0x47: 3, 0x43: 4}


def _parse_index(raw: Any) -> int:
    """解析 "0x6020" / "24608" / 24608 这类对象字典写法。"""
    if isinstance(raw, int):
        return raw
    return int(str(raw).strip(), 0)


class SocketCANBus:
    """最小 SocketCAN 总线：send/recv 接口与假总线（测试用）保持一致。

    recv(timeout) 返回 (arbitration_id, data) 或 None（超时）。
    """

    def __init__(self, channel: str) -> None:
        self.channel = channel
        self._sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self._sock.bind((channel,))

    def send(self, arbitration_id: int, data: bytes) -> None:
        frame = struct.pack("<IB3x8s", arbitration_id, len(data), bytes(data).ljust(8, b"\x00"))
        self._sock.send(frame)

    def recv(self, timeout: float) -> tuple[int, bytes] | None:
        self._sock.settimeout(timeout)
        try:
            frame, _addr = self._sock.recvfrom(16)
        except socket.timeout:
            return None
        can_id, dlc, data = struct.unpack("<IB3x8s", frame)
        return can_id, bytes(data[:dlc])

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


def read_sdo(bus: Any, node_id: int, index: int, subindex: int = 0, timeout: float = 0.20) -> int:
    """一次 expedited SDO upload，只读不写（与 demo.py 的 read_sdo 一致）。"""
    tx_id = 0x600 + node_id
    rx_id = 0x580 + node_id
    request = bytes([0x40, index & 0xFF, (index >> 8) & 0xFF, subindex, 0, 0, 0, 0])
    bus.send(tx_id, request)
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        msg = bus.recv(timeout=min(0.03, max(0.001, remaining)))
        if msg is None:
            continue
        arbitration_id, data = msg
        # 扩展帧忽略（demo 里是 msg.is_extended_id）。
        if arbitration_id & 0x80000000:
            continue
        if arbitration_id != rx_id:
            continue
        if len(data) != 8:
            continue
        returned_index = data[1] | (data[2] << 8)
        if returned_index != index or data[3] != subindex:
            continue
        if data[0] == 0x80:
            abort_code = int.from_bytes(data[4:8], "little")
            raise RuntimeError(
                f"SDO abort 0x{abort_code:08X} for 0x{index:04X}:{subindex:02X}"
            )
        if data[0] not in _SDO_SIZES:
            raise RuntimeError(
                f"Unsupported SDO response 0x{data[0]:02X} for 0x{index:04X}:{subindex:02X}"
            )
        size = _SDO_SIZES[data[0]]
        return int.from_bytes(data[4:4 + size], "little")

    raise TimeoutError(f"SDO timeout for node {node_id}, object 0x{index:04X}:{subindex:02X}")


@dataclass(frozen=True)
class CANPointConfig:
    name: str
    bus: str
    node: int
    idx_pos: int
    sidx_pos: int
    idx_resolution: int
    sidx_resolution: int
    idx_alarm: int = ALARM_INDEX
    sidx_alarm: int = ALARM_SUBINDEX
    parser_name: str = ""
    segs: SegmentMapping = SegmentMapping(())
    unit: str | None = None
    add: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bus": self.bus,
            "node": self.node,
            "dict": {
                "idx_pos": f"0x{self.idx_pos:04X}",
                "sidx_pos": f"0x{self.sidx_pos:02X}",
                "idx_resolution": f"0x{self.idx_resolution:04X}",
                "sidx_resolution": f"0x{self.sidx_resolution:02X}",
            },
            "parser": self.parser_name,
            "segs": [f"{s.source:g}@{s.target:g}" for s in self.segs.segments],
            "unit": self.unit,
        }


class CANPoint:
    """一个 CAN 滑台位移点：SDO 读到的毫米数再走公共换算。"""

    def __init__(self, config: CANPointConfig) -> None:
        self.config = config
        self.alive = False
        self.raw_position: int | None = None
        self.resolution_nm: int | None = None
        self.alarm: int | None = None
        self.raw_value: float | None = None  # 换算前：demo 算出的 position_mm
        self.value: float | None = None  # 换算后：segs.apply + add
        self.error: str = ""
        self.updated_at: float | None = None

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def unit(self) -> str | None:
        return self.config.unit

    def update(self, position_mm: float, resolution_nm: int, alarm: int, raw_position: int) -> None:
        # 公共换算，与 plc/vsp 同一套：segs.apply 后 +add，保留 3 位小数。
        self.raw_value = position_mm
        self.value = RawValueConverter(segs=self.config.segs, add=self.config.add).to_true(
            position_mm, round_digits=3
        )
        self.raw_position = raw_position
        self.resolution_nm = resolution_nm
        self.alarm = alarm
        self.alive = True
        self.error = ""
        self.updated_at = time.time()

    def mark_error(self, error: str) -> None:
        self.value = None
        self.alive = False
        self.error = error
        self.updated_at = time.time()

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bus": self.config.bus,
            "node": self.config.node,
            "alive": self.alive,
            "raw_position": self.raw_position,
            "resolution_nm": self.resolution_nm,
            "alarm": self.alarm,
            "raw_value": self.raw_value,
            "value": self.value,
            "unit": self.unit,
            "error": self.error,
            "updated_at": self.updated_at,
        }


def read_sensor(bus: Any, point: CANPoint, sdo_timeout: float) -> None:
    """读一个点（与 demo.py 的 read_sensor 一致，单点出错不影响其他点）。

    顺序不能换：先分辨率（校验 >0），再位置（转有符号 INT32），
    最后报警；位置毫米数 = 原始值 * 分辨率(nm) / 1_000_000。
    """
    cfg = point.config
    resolution_nm = read_sdo(bus, cfg.node, cfg.idx_resolution, cfg.sidx_resolution, timeout=sdo_timeout)
    if resolution_nm <= 0:
        raise ValueError(f"Invalid resolution: {resolution_nm}")
    raw = read_sdo(bus, cfg.node, cfg.idx_pos, cfg.sidx_pos, timeout=sdo_timeout)
    if raw >= 2**31:
        raw -= 2**32
    alarm = read_sdo(bus, cfg.node, cfg.idx_alarm, cfg.sidx_alarm, timeout=sdo_timeout)
    position_mm = raw * resolution_nm / 1_000_000.0
    point.update(position_mm, resolution_nm, alarm, raw)


class CANTable:
    """CAN 点表：自己的轮询线程，自己的总线，形态与 plc/vsp 对齐。"""

    def __init__(
        self,
        config_path: str | Path,
        sim: bool = False,
        bus_factory: Callable[[str], Any] | None = None,
    ) -> None:
        config_file = Path(config_path).resolve()
        data = json.loads(config_file.read_text(encoding="utf-8"))
        table_config = data.get("config") or {}
        raw_points: dict[str, dict[str, Any]] = data.get("pts") or {}

        self.config_path = config_file
        self.poll_interval_ms = int(table_config.get("poll_interval_ms", 300))
        self.sdo_timeout_ms = int(table_config.get("sdo_timeout_ms", 200))
        self.sim = bool(sim)
        self.broker = None
        self.alive = False
        self.last_poll_at: float | None = None
        self.last_error: str = ""
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._bus: Any | None = None
        self._bus_factory = bus_factory or SocketCANBus

        self.points: dict[str, CANPoint] = {}
        for name, point_data in raw_points.items():
            self.points[name] = CANPoint(self._parse_config(name, point_data))
        channels = {p.config.bus for p in self.points.values()}
        if len(channels) > 1:
            raise ValueError(f"CANTable 只支持单总线，配置文件里混了多个 bus：{sorted(channels)}")
        self.channel: str | None = next(iter(channels)) if channels else None

    @staticmethod
    def _parse_config(name: str, point_data: dict[str, Any]) -> CANPointConfig:
        obj = point_data.get("dict") or {}
        add_raw = point_data.get("add")
        return CANPointConfig(
            name=name,
            bus=str(point_data.get("bus") or "can0"),
            node=int(point_data.get("node")),
            idx_pos=_parse_index(obj.get("idx_pos", 0x6020)),
            sidx_pos=_parse_index(obj.get("sidx_pos", 0x01)),
            idx_resolution=_parse_index(obj.get("idx_resolution", 0x6005)),
            sidx_resolution=_parse_index(obj.get("sidx_resolution", 0x01)),
            idx_alarm=_parse_index(obj.get("idx_alarm", ALARM_INDEX)),
            sidx_alarm=_parse_index(obj.get("sidx_alarm", ALARM_SUBINDEX)),
            parser_name=str(point_data.get("parser") or "").strip(),
            segs=SegmentMapping.parse(point_data.get("segs")),
            unit=point_data.get("unit"),
            add=float(add_raw) if add_raw is not None else 0.0,
        )

    # -- 轮询线程（与 vsp 的 start/stop 同名，另给 plc 风格的别名） --

    def start(self) -> threading.Thread:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._thread
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._poll_loop, name="can-poller", daemon=True)
            self._thread.start()
            return self._thread

    def start_polling(self) -> threading.Thread:
        return self.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._close_bus()

    def stop_polling(self, timeout: float | None = 2.0) -> None:
        self.stop(timeout=timeout)

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _close_bus(self) -> None:
        bus, self._bus = self._bus, None
        if bus is not None:
            try:
                bus.close()
            except Exception:
                pass

    def _ensure_bus(self) -> Any:
        if self._bus is not None:
            return self._bus
        if self.sim:
            # CAN 的 sim 模式尚未定义：不编造假数据，让轮询标记错误，
            # 后续按真实 sim 方案（虚拟总线/回放）再补。
            raise RuntimeError("CAN sim 模式未定义，无法打开虚拟总线")
        if self.channel is None:
            raise RuntimeError("can.json 里没有点位，无法确定总线")
        self._bus = self._bus_factory(self.channel)
        return self._bus

    def _poll_loop(self) -> None:
        interval = self.poll_interval_ms / 1000.0
        print(f"can interval: {interval}")
        while not self._stop_event.is_set():
            started_at = time.time()
            self.poll_once()
            elapsed = time.time() - started_at
            self._stop_event.wait(max(0.0, interval - elapsed))

    def poll_once(self) -> None:
        any_success = False
        last_error = ""
        try:
            bus = self._ensure_bus()
        except Exception as exc:
            with self._lock:
                for point in self.points.values():
                    point.mark_error(str(exc))
                self.alive = False
                self.last_poll_at = time.time()
                self.last_error = str(exc)
            self._publish_poll_event()
            return

        for point in list(self.points.values()):
            try:
                read_sensor(bus, point, sdo_timeout=self.sdo_timeout_ms / 1000.0)
                any_success = True
            except Exception as exc:
                with self._lock:
                    point.mark_error(str(exc))
                last_error = str(exc)
                continue

        with self._lock:
            self.alive = any_success and bool(self.points)
            self.last_poll_at = time.time()
            self.last_error = last_error
        self._publish_poll_event()

    def _publish_poll_event(self) -> None:
        broker = self.broker
        if broker is not None:
            broker.publish(
                topic="can_poll",
                alive=self.alive,
                running=self.is_running(),
                last_poll_at=self.last_poll_at,
                error=self.last_error,
            )

    # -- 读 / 快照 / 标定写回（与 plc/vsp 同形态） --

    def read(self, name: str) -> float | None:
        with self._lock:
            return self.points[name].value

    def read_raw(self, name: str) -> float | None:
        with self._lock:
            return self.points[name].raw_value

    def get(self, name: str) -> CANPoint:
        return self.points[name]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "alive": self.alive,
                "running": self.is_running(),
                "last_poll_at": self.last_poll_at,
                "last_error": self.last_error,
                "points": {name: point.snapshot() for name, point in self.points.items()},
            }

    def describe(self) -> dict[str, dict[str, Any]]:
        return {name: point.config.to_dict() for name, point in self.points.items()}

    def update_by_id(self, name: str, segs: list[str], add: float | None = None) -> None:
        if name not in self.points:
            raise KeyError(name)
        seg_mapping = SegmentMapping.parse(segs)

        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        raw_points = payload.get("pts") or {}
        if name not in raw_points:
            raise KeyError(name)
        raw_points[name]["segs"] = list(segs)
        if add is not None:
            raw_points[name]["add"] = add
        self.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        point = self.points[name]
        old = point.config
        point.config = CANPointConfig(
            name=old.name,
            bus=old.bus,
            node=old.node,
            idx_pos=old.idx_pos,
            sidx_pos=old.sidx_pos,
            idx_resolution=old.idx_resolution,
            sidx_resolution=old.sidx_resolution,
            idx_alarm=old.idx_alarm,
            sidx_alarm=old.sidx_alarm,
            parser_name=old.parser_name,
            segs=seg_mapping,
            unit=old.unit,
            add=add if add is not None else old.add,
        )

    def reload(self) -> None:
        """原地重载 CAN 配置：不停止轮询线程，不替换实例（与 plc/vsp 一致）。"""
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        table_config = data.get("config") or {}
        raw_points: dict[str, dict[str, Any]] = data.get("pts") or {}

        new_points: dict[str, CANPoint] = {}
        for name, point_data in raw_points.items():
            new_points[name] = CANPoint(self._parse_config(name, point_data))
        channels = {p.config.bus for p in new_points.values()}
        if len(channels) > 1:
            raise ValueError(f"CANTable 只支持单总线，配置文件里混了多个 bus：{sorted(channels)}")

        with self._lock:
            self.poll_interval_ms = int(table_config.get("poll_interval_ms", 300))
            self.sdo_timeout_ms = int(table_config.get("sdo_timeout_ms", 200))
            self.points = new_points
            self.channel = next(iter(channels)) if channels else None
            self.alive = False
            self.last_poll_at = None
            self.last_error = ""
        # 总线通道可能变了：下次轮询重新打开，不在锁里关旧总线。
        self._close_bus()


def load_can(
    config_path: str | Path,
    sim: bool = False,
    bus_factory: Callable[[str], Any] | None = None,
) -> CANTable:
    """加载 CAN 点位表（与 load_pt / load_vsp 同形态）。"""
    return CANTable(config_path, sim=sim, bus_factory=bus_factory)
