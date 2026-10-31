"""协议自适应的 VSP 模拟器 (配合主程序 sim=true 使用).

背景: 主程序 sim 模式会把 vsp.json 全部 14 个点位临时重定向到同一个
localhost@10000, 但三类设备协议互不相同:

- 称重台 x4   : Modbus RTU 功能码 03, 二进制帧
- 激光 x8     : MEWTOCOL ASCII 文本 "%01#RMD**\\r"
- 压头横向 x2 : Modbus RTU 功能码 04, 二进制帧

只模拟称重台的模拟器喂不活另外两类: 激光指令无人应答 (empty payload),
压头指令回 Modbus 异常帧 (5 字节, 解析时报"字节数<6"), 两类点位每轮轮询
都失败, value 恒为 None, 上层 algo 读到的就是 None.

本模拟器在同一个端口上按请求内容分流应答, 三类协议都回合法帧,
数值带小幅游走, 方便观察刷新. 用法:

    python tools/sim_vsp.py [端口=10000]

然后在 app.ini 里打开 [sim] enable=true, 启动主程序即可.
Ctrl+C 退出.
"""

from __future__ import annotations

import random
import socket
import sys
import threading
import time

HEAD_BASE = 8041973  # 与 libs/vsp/core.py 的 head_x 解析保持一致

_lock = threading.Lock()
_state = {
    "weight": 11000.0,   # 称重台原始寄存器值 (4 字节无符号)
    "laser_mm": 182.5,   # 激光测距 mm
    "head_raw": HEAD_BASE + int(2053 / 6 * 4096),  # 压头: hex2dis 解出约 2053
}


def _walk(key: str, delta: float, lo: float, hi: float) -> float:
    with _lock:
        value = _state[key] + random.uniform(-delta, delta)
        _state[key] = max(lo, min(hi, value))
        return _state[key]


def crc16_modbus(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def answer_weight(req: bytes) -> bytes:
    """功能码 03: 回 2 个寄存器 (4 字节) 的称重原始值."""
    value = int(_walk("weight", 60, 9000, 13000))
    body = bytes([req[0], 0x03, 0x04]) + value.to_bytes(4, "big")
    return body + crc16_modbus(body)


def answer_head_x(req: bytes) -> bytes:
    """功能码 04: 回 2 个寄存器, 原始值围绕 HEAD_BASE 偏移, 解出约 2053.

    两个压头点在 sim 下共用同一端点和同一指令, 模拟器无法区分 1/2 号,
    回同一个原始值; 两点的最终读数差由各自的 add 标定决定 (-1253/-773),
    对流程联调足够. 需要区分时可在主程序里改走真实地址.
    """
    with _lock:
        raw = _state["head_raw"] + random.randint(-300, 300)
    body = bytes([req[0], 0x04, 0x04]) + int(raw).to_bytes(4, "big")
    return body + crc16_modbus(body)


def answer_write(req: bytes) -> bytes:
    """功能码 10 (清零等写多寄存器): 按 Modbus 标准回显 地址/数量."""
    body = req[:6]
    return body + crc16_modbus(body)


def answer_laser(req: bytes) -> bytes:
    """MEWTOCOL RMD 应答: %01$RMD<带符号7位, 1LSB=0.0001mm>**\\r."""
    mm = _walk("laser_mm", 0.4, 150.0, 220.0)
    raw = int(round(mm * 10000))
    return f"%01$RMD{raw:+08d}**\r".encode("ascii")


def dispatch(req: bytes) -> bytes | None:
    if not req:
        return None
    if req.startswith(b"%"):
        return answer_laser(req)
    if len(req) >= 2:
        func = req[1]
        if func == 0x03:
            return answer_weight(req)
        if func == 0x04:
            return answer_head_x(req)
        if func == 0x10:
            return answer_write(req)
        body = bytes([req[0], func | 0x80, 0x01])  # 未实现的功能码: 异常应答
        return body + crc16_modbus(body)
    return None


def handle(conn: socket.socket, addr) -> None:
    with conn:
        conn.settimeout(2.0)
        try:
            req = conn.recv(128)
        except socket.timeout:
            return
        if not req:
            return
        resp = dispatch(req)
        kind = "laser" if req.startswith(b"%") else f"modbus-{req[1]:02X}" if len(req) >= 2 else "?"
        print(f"[{time.strftime('%H:%M:%S')}] {addr} {kind:9s} req={req.hex(' ') if not req.startswith(b'%') else req!r} "
              f"-> {'无应答' if resp is None else resp.hex(' ') if not resp.startswith(b'%') else resp!r}")
        if resp is not None:
            conn.sendall(resp)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", port))
    server.listen(16)
    print(f"sim_vsp 协议自适应模拟器已启动: 0.0.0.0:{port} (weight/laser/head_x 三类协议)")
    try:
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\nsim_vsp 退出")
    finally:
        server.close()


if __name__ == "__main__":
    main()
