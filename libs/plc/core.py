from __future__ import annotations

import json
import math
import socket
import struct
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import logging

from _runtime import get_runtime
from guard import init as guard_init, guard_check

try:
    from segs import SegmentMapping
except ModuleNotFoundError:  # pragma: no cover - fallback for package imports
    from main.libs.segs import SegmentMapping

try:
    from convert import RawValueConverter
except ModuleNotFoundError:  # pragma: no cover - fallback for package imports
    from main.libs.convert import RawValueConverter

STATUS_OK = 0
STATUS_ERROR = 1
# INT/WORD:1寄存器 (有符号/无符号)  
# REAL/DWORD:2寄存器 (必须从偶数寄存器开始!!!, 也就是第0/2/4....)
SUPPORTED_TYPES = {"BOOL", "WORD", "INT", "REAL"}  
MAX_REGISTERS_PER_REQ = 125

@dataclass
class BaseAct:
    pt_name: str
    value: bool | int | float
    reset: bool

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "BaseAct":
        if not isinstance(raw, dict):
            raise TypeError(f"BaseAct raw must be dict, got {type(raw).__name__}")

        pt_name = str(raw.get("pt_name") or "").strip()
        if not pt_name:
            raise ValueError("BaseAct.pt_name is required")

        if "value" not in raw:
            raise ValueError("BaseAct.value is required")
        value = raw["value"]
        if type(value) not in (bool, int, float):
            raise TypeError("BaseAct.value must be bool, int, or float")

        reset_raw = raw.get("reset", False)
        if type(reset_raw) is not bool:
            raise TypeError("BaseAct.reset must be bool")

        return cls(pt_name=pt_name, value=value, reset=reset_raw)

@dataclass(frozen=True)
class Address:
    word: int
    bit: int | None = None

    @classmethod
    def parse(cls, raw: Any) -> "Address":
        text = str(raw).strip()
        if "." in text:
            word_text, bit_text = text.split(".", 1)
            word = int(word_text)
            bit = int(bit_text)
            if bit < 0 or bit > 15:
                raise ValueError(f"invalid bool bit: {text}")
            return cls(word=word, bit=bit)
        return cls(word=int(text), bit=None)


@dataclass(frozen=True)
class ReadGroup:
    start_word: int
    words: int


def words_for_type(point_type: str) -> int:
    if point_type == "REAL":
        return 2
    return 1


@dataclass()
class PLCPoint:
    name: str
    io: str
    point_type: str
    address: Address
    done: str | None
    segs: SegmentMapping
    add: float
    unit: str | None
    show: bool
    desc: str | None
    connection_ip: str
    connection_port: int
    slave_id: int
    timeout_ms: int
    _segs_ref: str | None = field(default=None, repr=False)

    raw_value: bool | int | None = field(
        init=False,
        default=None,
        repr=False,
    )
    
    @property
    def word_count(self) -> int:
        return words_for_type(self.point_type)

    @property
    def byte_length(self) -> int:
        return self.word_count * 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "io": self.io,
            "type": self.point_type,
            "addr-2byte": (
                f"{self.address.word}.{self.address.bit}"
                if self.address.bit is not None
                else self.address.word
            ),
            "done": self.done,
            "segs": [f"{segment.source:g}@{segment.target:g}" for segment in self.segs.segments],
            "unit": self.unit,
        }

    def read(self, table: "PLCPointTable") -> Any:
        self.raw_value = table.read_raw_point(self)
        _value = self._to_true_value(self.raw_value, table)
        if (self.point_type == "REAL" or self.point_type == "INT"):
            _value = round(_value,3)
        return _value

    def write(self, value: Any, table: "PLCPointTable") -> None:
        if self.point_type == "BOOL":
            table.write_bool_point(self, self._validate_bool(value))
        else:
            if self.point_type == "INT":
                # INT 为有符号：负数按补码下发（_encode_registers 内部 & 0xFFFF）
                value = self._to_raw_value(value, table)
            elif self.point_type == "WORD":
                value = int(value)
            table.write_registers(self.address.word, self._encode_registers(value))

    def _to_raw_value(self, value: Any, table: "PLCPointTable") -> int:
        """将用户输入的真值转换为 PLC 原始值"""
        float_value = float(value)
        segs = self._get_reference_segs(table)
        # 公共换算：真值 -> 原始值（apply_reverse 后 +add，与原行为一致）
        return int(RawValueConverter(segs=segs, add=self.add).to_raw(float_value))

    def _get_reference_segs(self, table: "PLCPointTable"):
        """
        获取用于值转换的 segs
        如果配置了 _segs_ref 引用另一个点位，则使用该点位的 segs
        """
        if self._segs_ref and self._segs_ref in table.points:
            return table.points[self._segs_ref].segs

        return self.segs

    def _decode_registers(self, registers: list[int]) -> Any:
        raw = b"".join(struct.pack(">H", register & 0xFFFF) for register in registers)
        if self.point_type == "BOOL":
            word = struct.unpack(">H", raw[:2])[0]
            return bool((word >> int(self.address.bit or 0)) & 0x01)
        if self.point_type == "WORD":
            return struct.unpack(">H", raw[:2])[0]
        if self.point_type == "INT":
            return struct.unpack(">h", raw[:2])[0]
        if self.point_type == "REAL":
            # REAL uses standard Modbus word order: high word first, low word second.
            return struct.unpack(">f", raw)[0]
        raise TypeError(f"unsupported point type: {self.point_type}")

    def _to_true_value(self, raw_value: Any, table: "PLCPointTable") -> Any:
        if self.point_type == "BOOL":
            return raw_value

        segs = self._get_reference_segs(table)
        # 公共换算：原始值 -> 真值（segs.apply 后 +add）
        value = RawValueConverter(segs=segs, add=self.add).to_true(raw_value)

        # if self.point_type in {"WORD", "INT"} and not self.segs.segments:
        #     print(f"{self.name} NO SEGS!!!")
        #     return int(raw_value)

        return value

    def _encode_registers(self, value: Any) -> list[int]:
        if self.point_type == "WORD":
            typed_value = self._validate_word(value)
            return [typed_value]
        if self.point_type == "INT":
            typed_value = self._validate_int(value)
            return [typed_value & 0xFFFF]
        if self.point_type == "REAL":
            typed_value = self._validate_real(value)
            raw = struct.pack(">f", typed_value)
            hi = struct.unpack(">H", raw[0:2])[0]
            lo = struct.unpack(">H", raw[2:4])[0]
            return [hi, lo]
        raise TypeError(f"{self.name}: write is unsupported for {self.point_type}")

    def _validate_bool(self, value: Any) -> bool:
        if type(value) is not bool:
            raise TypeError(f"{self.name}: BOOL only accepts bool")
        return value

    def _validate_word(self, value: Any) -> int:
        if type(value) is not int:
            raise TypeError(f"{self.name}: WORD only accepts int")
        if value < 0 or value > 0xFFFF:
            raise ValueError(f"{self.name}: WORD out of range 0..65535")
        return value

    def _validate_int(self, value: Any) -> int:
        if type(value) is not int:
            raise TypeError(f"{self.name}: INT only accepts int")
        if value < -0x8000 or value > 0x7FFF:
            raise ValueError(f"{self.name}: INT out of range -32768..32767")
        return value

    def _validate_real(self, value: Any) -> float:
        if type(value) not in (int, float):
            raise TypeError(f"{self.name}: REAL only accepts float")
        return float(value)


class ModbusTCPClient:
    def __init__(self, host: str, port: int, slave_id: int, timeout: float = 1.0) -> None:
        self.host = host
        self.port = port
        self.slave_id = slave_id
        self.timeout = timeout
        self._transaction_id = 0
        self._sock: socket.socket | None = None

    def __enter__(self) -> "ModbusTCPClient":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def open(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        payload = struct.pack(">HH", address, count)
        response = self._request(0x03, payload)
        if not response or response[0] != count * 2:
            raise IOError("invalid modbus read response")
        data = response[1:]
        return [struct.unpack(">H", data[index:index + 2])[0] for index in range(0, len(data), 2)]

    def write_registers(self, address: int, values: list[int]) -> None:
        if len(values) == 1:
            payload = struct.pack(">HH", address, values[0])
            response = self._request(0x06, payload)
            expected = struct.pack(">HH", address, values[0])
            if response != expected:
                raise IOError("modbus single-write echo mismatch")
            return

        body = b"".join(struct.pack(">H", value) for value in values)
        payload = struct.pack(">HHB", address, len(values), len(body)) + body
        response = self._request(0x10, payload)
        expected = struct.pack(">HH", address, len(values))
        if response != expected:
            raise IOError("modbus multi-write echo mismatch")

    def write_bool_point(self, point: PLCPoint, value: bool) -> None:
        current = self.read_holding_registers(point.address.word, 1)[0]
        bit = int(point.address.bit or 0)
        if value:
            current |= 1 << bit
        else:
            current &= ~(1 << bit)
        self.write_registers(point.address.word, [current])

    def _request(self, function_code: int, payload: bytes) -> bytes:
        self.open()
        assert self._sock is not None
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        header = struct.pack(">HHHB", self._transaction_id, 0, len(payload) + 2, self.slave_id)
        self._sock.sendall(header + bytes([function_code]) + payload)

        mbap = self._recv_exact(7)
        transaction_id, protocol_id, length, unit_id = struct.unpack(">HHHB", mbap)
        if transaction_id != self._transaction_id or protocol_id != 0 or unit_id != self.slave_id:
            raise IOError("invalid modbus MBAP header")
        pdu = self._recv_exact(length - 1)
        response_function = pdu[0]
        if response_function == function_code + 0x80:
            raise IOError(f"modbus exception code: {pdu[1]}")
        if response_function != function_code:
            raise IOError("unexpected modbus function code")
        return pdu[1:]

    def _recv_exact(self, size: int) -> bytes:
        assert self._sock is not None
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = self._sock.recv(remaining)
            if not chunk:
                raise IOError("modbus connection closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def _parse_segs_with_ref(raw_segs: Any) -> tuple[SegmentMapping, str | None]:
    """
    解析 segs 配置，支持两种格式：
    1. 普通 segs: ["100@200", "200@400"] 或 null
    2. 点位引用: ["点位名称"] (没有 @ 符号)

    返回: (SegmentMapping, 引用点位名称 或 None)
    """
    if raw_segs is None:
        return SegmentMapping(()), None

    if not isinstance(raw_segs, list):
        return SegmentMapping(()), None

    if not raw_segs:
        return SegmentMapping(()), None

    first_item = str(raw_segs[0]).strip()

    if "@" not in first_item:
        return SegmentMapping(()), first_item

    try:
        return SegmentMapping.parse(raw_segs), None
    except Exception:
        return SegmentMapping(()), None
        assert self._sock is not None
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = self._sock.recv(remaining)
            if not chunk:
                raise IOError("modbus connection closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


class PLCPointTable:
    """Manages a collection of PLCPoint instances with polling, events, and composed actions.
    """

    def __init__(self, config_path: str | Path, sim: bool) -> None:
        config_file = Path(config_path).resolve()
        data = json.loads(config_file.read_text(encoding="utf-8"))

        connection = data["config"]
        raw_points: dict[str, dict[str, Any]] = data["pts"]

        self.sim = sim
        self.config_path = config_file
        self.connection_ip = connection["ip"] if self.sim==False else connection["ip_sim"]
        self.connection_port = int(connection["port"])
        self.slave_id = int(connection["slave_id"])
        self.timeout_ms = int(connection.get("timeout_ms", 1000))
        self.reconnect_interval_ms = int(connection.get("reconnect_interval_ms", 3000))
        self.poll_interval_ms = int(connection.get("poll_interval_ms", 500))
        self.points: dict[str, PLCPoint] = {}
        self.read_groups: list[ReadGroup] = []
        self.broker = None  
        self.alive = False
        self.last_poll_at: float | None = None
        self.last_error: str = ""
        self._status_code = STATUS_ERROR
        self._lock = threading.RLock()
        self._io_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._action_stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._cache_words: dict[int, int] = {}
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self.done_evaluator: Callable[[str], bool] | None = None
        self._client = ModbusTCPClient(
            host=self.connection_ip,
            port=self.connection_port,
            slave_id=self.slave_id,
            timeout=self.timeout_ms / 1000.0 if self.timeout_ms > 0 else 1.0,
        )
        self._last_connect_try = 0.0

        occupied_words: set[int] = set()
        for name, point_data in raw_points.items():
            point_type = point_data["type"].upper()
            if point_type not in SUPPORTED_TYPES:
                raise TypeError(f"{name}: unsupported point type {point_type}")
            segs, segs_ref = _parse_segs_with_ref(point_data.get("segs"))
            point = PLCPoint(
                name=name,
                io=point_data["io"],
                point_type=point_type,
                address=Address.parse(point_data["addr-2byte"]),
                done=None,
                segs=segs,
                add=point_data.get("add", 0),
                unit=point_data.get("unit"),
                desc=point_data.get("desc"),
                show=point_data.get("show", True),
                connection_ip=self.connection_ip,
                connection_port=self.connection_port,
                slave_id=self.slave_id,
                timeout_ms=self.timeout_ms,
                _segs_ref=segs_ref,
            )
            self.points[name] = point
            for offset in range(point.word_count):
                occupied_words.add(point.address.word + offset)

        self.read_groups = self._build_read_groups(occupied_words)

    def open(self) -> "PLCPointTable":
        if not self.is_running():
            self.poll_once()
        return self

    def close(self) -> None:
        self.stop_polling()
        with self._io_lock:
            self._client.close()

    def __enter__(self) -> "PLCPointTable":
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def reload(self) -> None:
        """原地重载 PLC 配置：仅更新内部数据，不停止轮询线程，不替换实例。

        所有外部引用（broker、done_evaluator、runtime 中的实例）均保持有效。
        """
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        connection = data["config"]
        raw_points: dict[str, dict[str, Any]] = data["pts"]

        # 更新连接参数
        self.connection_ip = connection["ip"] if self.sim==False else connection["ip_sim"]
        self.connection_port = int(connection["port"])
        self.slave_id = int(connection["slave_id"])
        self.timeout_ms = int(connection.get("timeout_ms", 1000))
        self.reconnect_interval_ms = int(connection.get("reconnect_interval_ms", 3000))
        self.poll_interval_ms = int(connection.get("poll_interval_ms", 500))

        # 构建新点位表和读取分组（锁外完成，不影响轮询线程）
        new_points: dict[str, PLCPoint] = {}
        occupied_words: set[int] = set()
        for name, point_data in raw_points.items():
            point_type = point_data["type"].upper()
            if point_type not in SUPPORTED_TYPES:
                raise TypeError(f"{name}: unsupported point type {point_type}")
            segs, segs_ref = _parse_segs_with_ref(point_data.get("segs"))
            point = PLCPoint(
                name=name,
                io=point_data["io"],
                point_type=point_type,
                address=Address.parse(point_data["addr-2byte"]),
                done=None,
                segs=segs,
                unit=point_data.get("unit"),
                desc=point_data.get("desc"),
                add=point_data.get("add", 0),
                show=point_data.get("show", True),
                connection_ip=self.connection_ip,
                connection_port=self.connection_port,
                slave_id=self.slave_id,
                timeout_ms=self.timeout_ms,
                _segs_ref=segs_ref,
            )
            new_points[name] = point
            for offset in range(point.word_count):
                occupied_words.add(point.address.word + offset)
        new_read_groups = self._build_read_groups(occupied_words)

        # 原子交换数据
        # _io_lock：防止轮询线程在 _ensure_connected 和 read 之间被切换 client
        with self._io_lock:
            self._client.close()
            self._client = ModbusTCPClient(
                host=self.connection_ip,
                port=self.connection_port,
                slave_id=self.slave_id,
                timeout=self.timeout_ms / 1000.0 if self.timeout_ms > 0 else 1.0,
            )
            self._last_connect_try = 0.0

            with self._lock:
                self.points = new_points
                self.read_groups = new_read_groups
                self._cache_words.clear()
                self.alive = False
                self.last_error = ""
                self._status_code = STATUS_ERROR

    def __getitem__(self, name: str) -> PLCPoint:
        return self.points[name]

    # ------------------------------------------------------------------ #
    # Polling thread
    # ------------------------------------------------------------------ #

    def start_polling(self) -> threading.Thread:
        """Start the background poll loop."""
        guard_init(get_runtime())

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._thread
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._poll_loop, name="plc-poller", daemon=True
            )
            self._thread.start()
            return self._thread

    def stop_polling(self, timeout: float | None = 2.0) -> None:
        """Stop the background poll loop."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    # ------------------------------------------------------------------ #
    # Basic read / write
    # ------------------------------------------------------------------ #

    def read(self, name: str) -> Any:
        return self.points[name].read(self)

    def write(self, name: str, value: Any) -> None:
        self.points[name].write(value, self)

    def set_done(self, name: str, done: str | None) -> None:
        if name not in self.points:
            raise KeyError(name)
        if done is not None:
            done = str(done).strip() or None

        point = self.points[name]
        self.points[name] = PLCPoint(
            name=point.name,
            io=point.io,
            point_type=point.point_type,
            address=point.address,
            done=done,
            segs=point.segs,
            unit=point.unit,
            desc=point.desc,
            add=point.add,
            show=point.show,
            connection_ip=point.connection_ip,
            connection_port=point.connection_port,
            slave_id=point.slave_id,
            timeout_ms=point.timeout_ms,
        )

    # ------------------------------------------------------------------ #
    # Composed actions (bool output points only)
    # ------------------------------------------------------------------ #

    def act(
        self,
        actlist: list[BaseAct],
        watch_done: bool = True,
    ) -> None:
        if not actlist:
            return

        self._action_stop_event.clear()
        normalized_actlist: list[BaseAct] = []
        for each_raw in actlist:
            each = each_raw if isinstance(each_raw, BaseAct) else BaseAct.parse(each_raw)
            point = self.points[each.pt_name]
            # SB逻辑居然i都可以写!
            # if point.io != "o":
            #     if self.broker is not None: self.broker.publish(topic="plc_act_begin", msg=f"执行单元类型为i,不合法! {point.name}")
            #     return
            normalized_actlist.append(each)

        self._process_actlist(normalized_actlist, watch_done=watch_done)

    def start(self, pt_name: str, reset: bool = False) -> None:
        self.act([BaseAct(pt_name=pt_name, value=True, reset=reset)])

    def stop(self, pt_name: str) -> None:
        self.act([BaseAct(pt_name=pt_name, value=False, reset=False)])

    def cancel_pending_actions(self) -> None:
        self._action_stop_event.set()

    def _process_actlist(self, actlist: list[BaseAct], watch_done: bool = True) -> None:
        if self.broker is not None: self.broker.publish(topic="plc_act_end", msg="PLC并行开始")
        workers: list[threading.Thread] = []
        for index, act in enumerate(actlist):
            worker = threading.Thread(
                target=self._process_one_act,
                args=(act, watch_done),
                daemon=True,
                name=f"plc-act-worker-{index}",
            )
            worker.start()
            workers.append(worker)

        for worker in workers:
            worker.join()
        self._action_stop_event.clear()
        if self.broker is not None: self.broker.publish(topic="plc_act_end", msg="PLC并行完成")
        

    def _process_one_act(self, act: BaseAct, watch_done: bool = True) -> None:
        self._act(act.pt_name, act.value, act.reset, watch_done=watch_done)

    # ------------------------------------------------------------------ #
    # Action internals
    # ------------------------------------------------------------------ #

    def _watch_done(self, point: PLCPoint, poll_interval: float = 0.5) -> None:
        """Block until a done point goes True or the point itself resets to False."""
        while True:
            if self._action_stop_event.is_set():
                return
            if point.done and self._evaluate_done(point.done):
                return
            if point.read(self) is False:
                return
            if self._action_stop_event.wait(1):
                return
            

    def _evaluate_done(self, expression: str) -> bool:
        if self.done_evaluator is not None:
            return bool(self.done_evaluator(expression))
        return self._is_done_condition_met(expression)

    def _is_done_condition_met(self, expression: str) -> bool:
        pt_name, operator, expected = self._parse_done_expression(expression)
        actual = self.points[pt_name].read(self)
        expected_value = self._coerce_done_value(expected)

        if operator == "=":
            if isinstance(expected_value, bool):
                return actual is expected_value
            if isinstance(expected_value, (int, float)) and isinstance(actual, (int, float)) and not isinstance(actual, bool):
                return math.isclose(float(actual), float(expected_value), rel_tol=1e-9, abs_tol=1e-6)
            return str(actual).strip() == str(expected_value).strip()

        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False
        if not isinstance(expected_value, (int, float)) or isinstance(expected_value, bool):
            raise TypeError(f"done expression requires numeric rhs for '{operator}': {expression!r}")
        if operator == ">":
            return float(actual) > float(expected_value)
        if operator == "<":
            return float(actual) < float(expected_value)
        raise ValueError(f"unsupported done operator: {operator}")

    def _parse_done_expression(self, expression: str) -> tuple[str, str, str]:
        text = str(expression).strip()
        if not text:
            raise ValueError("done expression is empty")
        for operator in ("=", ">", "<"):
            if operator not in text:
                continue
            left, right = text.split(operator, 1)
            pt_name = left.strip()
            expected = right.strip()
            if not pt_name or not expected:
                raise ValueError(f"invalid done expression: {expression!r}")
            if pt_name not in self.points:
                raise KeyError(pt_name)
            return pt_name, operator, expected
        raise ValueError(f"invalid done expression: {expression!r}")

    @staticmethod
    def _coerce_done_value(raw: str) -> Any:
        text = str(raw).strip()
        lowered = text.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        try:
            number = float(text)
        except ValueError:
            return text
        if number.is_integer():
            return int(number)
        return number

    def _act(
        self,
        pt_name: str,
        value: bool | int | float,
        reset: bool,
        watch_done: bool = True,
    ) -> None:
        try:
            self.write(pt_name, value)
            if self.broker is not None: self.broker.publish(topic="plc_baseact_begin", msg=f" BaseAct写入完成:{pt_name}--->{value}")
            if watch_done and self.points[pt_name].point_type == "BOOL" and value is True and self.points[pt_name].done:
                self._watch_done(self.points[pt_name])
                if self._action_stop_event.is_set():
                    self.write(pt_name, False)
                    return
            if self.points[pt_name].point_type == "BOOL" and reset is True:
                self.write(pt_name, False)
            if self.broker is not None: self.broker.publish(topic="plc_baseact_end", msg=f" BaseAct监控完毕:{pt_name}--->{value}")
        except Exception as exc:
            if self.broker is not None: self.broker.publish(topic="plc_baseact_error", msg=f" BaseAct出错:{pt_name}--->{value}")

    def read_raw_point(self, point: PLCPoint) -> Any:
        with self._lock:
            missing_words = [
                point.address.word + offset
                for offset in range(point.word_count)
                if point.address.word + offset not in self._cache_words
            ]
        # 方案B: 在锁外尝试 poll_once，避免与后台线程死锁
        if missing_words:
            # 检查连接是否已建立（锁外检查，不阻塞）
            sock_exists = self._client._sock is not None
            if sock_exists:
                try:
                    self.poll_once()
                except Exception:
                    pass  # 忽略 poll_once 的错误，使用过期缓存

        with self._lock:
            still_missing = [
                point.address.word + offset
                for offset in range(point.word_count)
                if point.address.word + offset not in self._cache_words
            ]
            if still_missing:
                error = self.last_error or f"missing cached words: {still_missing}"
                raise IOError(f"{point.name}: plc read failed: {error}")
            registers = [
                self._cache_words[point.address.word + offset]
                for offset in range(point.word_count)
            ]
        return point._decode_registers(registers)

    def read_status_code(self) -> int:
        with self._lock:
            return self._status_code

    def is_connected(self) -> bool:
        return self.read_status_code() == STATUS_OK

    def write_registers(self, address: int, values: list[int]) -> None:
        with self._io_lock:
            if not self._ensure_connected_locked():
                logging.error(f"PLC通讯失败,地址[{address}]写入失败!")
            try:
                self._client.write_registers(address, values)
            except OSError:
                self._handle_io_failure_locked()
                raise
        self.poll_once()

    def write_bool_point(self, point: PLCPoint, value: bool) -> None:
        with self._io_lock:
            if not self._ensure_connected_locked():
                logging.error(
                    "PLC通讯失败,点位[%s]地址[%s.%s]写入失败!",
                    point.name, point.address.word, point.address.bit,
                )
            try:
                self._client.write_bool_point(point, value)
            except OSError:
                self._handle_io_failure_locked()
                raise
        if not point.name.endswith("限位"):
            self.poll_once()

    def write_word(self, word_address: int, value: int) -> None:
        """向指定字地址写入一个 0..65535 的数值，写入 0 即整字清零。

        复用 _io_lock 与连接管理，不影响其他功能。
        """
        if not isinstance(value, int):
            raise TypeError(f"write_word: value must be int, got {type(value).__name__}")
        if value < 0 or value > 0xFFFF:
            raise ValueError(f"write_word: value out of range 0..65535, got {value}")

        with self._io_lock:
            if not self._ensure_connected_locked():
                logging.error(f"PLC通讯失败,字地址[{word_address}]写入失败!")
                raise IOError(f"PLC未连接,无法写字地址[{word_address}]")
            try:
                self._client.write_registers(word_address, [value])
            except OSError:
                self._handle_io_failure_locked()
                raise
        self.poll_once()

    def describe(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                **point.to_dict(),
                "word_count": point.word_count,
            }
            for name, point in self.points.items()
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "alive": self.alive,
                "running": self.is_running(),
                "last_poll_at": self.last_poll_at,
                "last_error": self.last_error,
                "status_code": self._status_code,
                "read_groups": [
                    {"start_word": group.start_word, "words": group.words}
                    for group in self.read_groups
                ],
                "points": {
                    name: {
                        **point.to_dict(),
                        "value": point.read(self),
                    }
                    for name, point in self.points.items()
                    if all(
                        point.address.word + offset in self._cache_words
                        for offset in range(point.word_count)
                    )
                },
            }

    def poll_once(self) -> None:
        """方案B: 在锁外尝试连接，只在读取寄存器时持锁，避免阻塞"""
        if not self.read_groups:
            with self._lock:
                self.alive = False
                self.last_poll_at = time.time()
                self.last_error = "pts is empty"
                self._status_code = STATUS_ERROR
            self._publish_poll_event()
            return

        # 方案B: 在锁外尝试连接/检查连接状态
        connected = self._ensure_connected_locked()
        if not connected:
            with self._lock:
                self.alive = False
                self.last_poll_at = time.time()
                self.last_error = "PLC reconnect backoff active"
                self._status_code = STATUS_ERROR
            self._publish_poll_event()
            return

        buffer: dict[int, int] = {}
        try:
            # 只在读取寄存器时持锁，不会在连接时阻塞其他线程
            with self._io_lock:
                for group in self.read_groups:
                    registers = self._client.read_holding_registers(group.start_word, group.words)
                    for offset, value in enumerate(registers):
                        buffer[group.start_word + offset] = value
        except Exception as exc:
            with self._io_lock:
                self._handle_io_failure_locked()
            with self._lock:
                self.alive = False
                self.last_poll_at = time.time()
                self.last_error = str(exc)
                self._status_code = STATUS_ERROR
            self._publish_poll_event()
            return

        with self._lock:
            self._cache_words = buffer
            self.alive = True
            self.last_poll_at = time.time()
            self.last_error = ""
            self._status_code = STATUS_OK
        self._publish_poll_event()

    def update_by_id(self, name: str, segs: list[str] | None = None, add: float | None = None) -> None:
        if name not in self.points:
            raise KeyError(name)
        seg_mapping = SegmentMapping.parse(segs) if segs is not None else None

        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        raw_points = payload.get("pts") or {}
        if name not in raw_points:
            raise KeyError(name)

        if segs is not None:
            raw_points[name]["segs"] = list(segs)
        if add is not None:
            raw_points[name]["add"] = add
        self.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        point = self.points[name]
        new_add = add if add is not None else point.add
        self.points[name] = PLCPoint(
            name=point.name,
            io=point.io,
            point_type=point.point_type,
            address=point.address,
            done=point.done,
            segs=seg_mapping if seg_mapping is not None else point.segs,
            unit=point.unit,
            add=new_add,
            desc=point.desc,
            show=point.show,
            connection_ip=point.connection_ip,
            connection_port=point.connection_port,
            slave_id=point.slave_id,
            timeout_ms=point.timeout_ms,
        )

    @staticmethod
    def _build_read_groups(words: set[int]) -> list[ReadGroup]:
        if not words:
            return []

        sorted_words = sorted(words)
        groups: list[ReadGroup] = []
        start = sorted_words[0]
        end = sorted_words[0]

        def flush() -> None:
            groups.append(ReadGroup(start_word=start, words=end - start + 1))

        for next_word in sorted_words[1:]:
            if next_word - start + 1 <= MAX_REGISTERS_PER_REQ:
                end = next_word
                continue
            flush()
            start = next_word
            end = next_word
        flush()
        return groups

    def _poll_loop(self) -> None:
        interval = self.poll_interval_ms / 1000.0
        while not self._stop_event.is_set():
            started_at = time.time()
            self.poll_once()

            # 执行安全检查
            if self.alive:
                guard_check()

            elapsed = time.time() - started_at
            self._stop_event.wait(max(0.0, interval - elapsed))

    def _ensure_connected_locked(self) -> bool:
        """确保已连接。返回 True 表示已连接或重连成功，False 表示在冷却期内。"""
        now = time.monotonic()
        if self._client._sock is not None:
            return True
        reconnect_interval = 1
        if reconnect_interval > 0 and now - self._last_connect_try < reconnect_interval:
            return False
        self._last_connect_try = now
        try:
            self._client.open()
        except Exception as exc:
            logging.warning("重连接plc失败: %s", exc)
            return False
        return True

    def _handle_io_failure_locked(self) -> None:
        self._client.close()

    def _publish_poll_event(self) -> None:
        with self._lock:
            kwargs: dict[str, Any] = dict(
                alive=self.alive,
                running=self.is_running(),
                last_poll_at=self.last_poll_at,
                status_code=self._status_code,
                error=self.last_error,
            )
        if self.broker is not None:
            self.broker.publish(topic="plc_poll", **kwargs)

    def _emc_stop(self):
        def _emc_stop_worker():
            try:
                logging.info("急停事件: 启动软急停流程")

                # 1. 读取关键实时数据
                load_p1 = self.read("加载压力1")
                load_p2 = self.read("加载压力2")
                head_y1 = self.read("加载头垂向位移1")
                head_y2 = self.read("加载头垂向位移2")
                air_p1 = self.read("气压采集1")
                air_p2 = self.read("气压采集2")
                logging.info(
                    f"急停数据: 加载力=({load_p1},{load_p2}), 位移=({head_y1},{head_y2}), 气压=({air_p1},{air_p2})"
                )

                def _wait_signal(name: str, timeout: float = 120.0, interval: float = 0.5) -> bool:
                    """在子线程内轮询等待PLC信号,不阻塞主程序"""
                    elapsed = 0.0
                    while elapsed < timeout:
                        val = self.read(name)
                        if val is True:
                            return True
                        time.sleep(interval)
                        elapsed += interval
                    return False

                def _clear_words():
                    """将地址60-64全部置0"""
                    for addr in [25,26,27,28,29,60,61,62,63,64]:
                        self.write_word(addr, 0)
                    logging.info("PLC字地址60-64已清零")

                # _clear_words()

                # 有气则排气
                max_air = max(
                    air_p1 if isinstance(air_p1, (int, float)) else 0,
                    air_p2 if isinstance(air_p2, (int, float)) else 0,
                )
                if max_air > 10:
                    logging.info(f"气压({max_air})>5, 启动排气")
                    self.write("空气弹簧放气", True)
                    time.sleep(1)
                    if _wait_signal("空气弹簧放气@完成"):
                        logging.info("空气弹簧放气完成")
                    else:
                        logging.warning("空气弹簧放气等待超时")

                # 停止压磅保持
                self.write("压磅中止", True)
                time.sleep(2)

                # 排完气,清零plc
                _clear_words()

                # 力工退
                self.write("设定加载头1加载力", 5)
                self.write("设定加载头2加载力", 5)
                time.sleep(0.5)
                self.write("力工退", True)
                time.sleep(5)

                if self.read("加载压力1") > 10.0:
                    if _wait_signal("快退加载装置@完成"):
                        logging.info("快退加载装置完成")
                    else:
                        logging.warning("快退加载装置等待超时")

                # 压头收回
                # if self.read("加载头垂向位移1") > 15.0 or self.read("加载头垂向位移2") > 15.0:
                #     self.write("设定加载头1快进垂向位移", 5)
                #     self.write("设定加载头2快进垂向位移", 5)
                #     self.write("快退加载装置", True)
                #     time.sleep(0.5)
                #     if _wait_signal("快退加载装置@完成"):
                #         logging.info("快退加载装置完成")
                #     else:
                #         logging.warning("快退加载装置等待超时")

                # 最后清零plc
                _clear_words()

                logging.info("软急停流程执行完毕")
            except Exception as e:
                logging.exception(f"紧急停止失败: {e}")

        threading.Thread(target=_emc_stop_worker, daemon=True, name="emc-stop-worker").start()

    def clear(self):
        """将地址60-64全部置0"""
        for addr in [25,26,27,28,29,60,61,62,63,64]:
            self.write_word(addr, 0)
        logging.info("PLC字地址已清零")


def load_pt(config_path: str | Path, sim:bool=False) -> PLCPointTable:
    return PLCPointTable(config_path, sim)
