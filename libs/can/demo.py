
#!/usr/bin/env python3
"""
TR-Electronic LMP 48 multi-sensor reader
Ubuntu + python-can + SocketCAN

CAN interface: can0
Baudrate:      500 kbit/s (configure separately with ip link)
CANopen nodes: 1, 2, 3, 4

Read-only SDO objects:
  0x6020:01 - Actual position (INTEGER32)
  0x6005:01 - Position resolution (verify against device manual)
  0x6503:00 - Alarm status (verify against device manual)
"""

import argparse
import time
import signal
import sys
from dataclasses import dataclass

import can

CHANNEL = "can0"
NODE_IDS = [1, 2, 3, 4]

POSITION_INDEX = 0x6020
POSITION_SUBINDEX = 0x01

RESOLUTION_INDEX = 0x6005
RESOLUTION_SUBINDEX = 0x01

ALARM_INDEX = 0x6503
ALARM_SUBINDEX = 0x00

SDO_TIMEOUT = 0.20
REFRESH_INTERVAL = 0.10
running = True


@dataclass
class SensorData:
    node_id: int
    position_mm: float = 0.0
    raw_position: int = 0
    resolution_nm: int = 0
    alarm: int = 0
    updated_at: float = 0.0
    error: str = "Not read"


def stop_handler(signum, frame):
    global running
    running = False


def read_sdo(bus, node_id, index, subindex=0, timeout=SDO_TIMEOUT):
    """Perform an expedited SDO upload. No object is written."""
    tx_id = 0x600 + node_id
    rx_id = 0x580 + node_id

    request = can.Message(
        arbitration_id=tx_id,
        is_extended_id=False,
        data=[
            0x40,
            index & 0xFF,
            (index >> 8) & 0xFF,
            subindex,
            0, 0, 0, 0
        ]
    )

    bus.send(request)
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        msg = bus.recv(timeout=min(0.03, max(0.001, deadline - time.monotonic())))

        if msg is None:
            continue

        # Ignore unrelated frames.
        if msg.is_extended_id or msg.arbitration_id != rx_id:
            continue

        if len(msg.data) != 8:
            continue

        data = bytes(msg.data)
        returned_index = data[1] | (data[2] << 8)

        if returned_index != index or data[3] != subindex:
            continue

        if data[0] == 0x80:
            abort_code = int.from_bytes(data[4:8], "little")
            raise RuntimeError(
                f"SDO abort 0x{abort_code:08X} "
                f"for 0x{index:04X}:{subindex:02X}"
            )

        # Expedited SDO upload response:
        # 0x4F = 1 byte, 0x4B = 2, 0x47 = 3, 0x43 = 4.
        sizes = {0x4F: 1, 0x4B: 2, 0x47: 3, 0x43: 4}
        if data[0] not in sizes:
            raise RuntimeError(
                f"Unsupported SDO response 0x{data[0]:02X} "
                f"for 0x{index:04X}:{subindex:02X}"
            )

        size = sizes[data[0]]
        return int.from_bytes(data[4:4 + size], "little")

    raise TimeoutError(
        f"SDO timeout for node {node_id}, "
        f"object 0x{index:04X}:{subindex:02X}"
    )


def read_sensor(bus, sensor):
    """Read one sensor. An error here does not stop other nodes."""
    node = sensor.node_id

    try:
        # Read position resolution (nanometers per count).
        resolution_nm = read_sdo(
            bus, node, RESOLUTION_INDEX, RESOLUTION_SUBINDEX
        )

        if resolution_nm <= 0:
            raise ValueError(f"Invalid resolution: {resolution_nm}")

        # Read actual position (INTEGER32).
        raw = read_sdo(
            bus, node, POSITION_INDEX, POSITION_SUBINDEX
        )

        # Convert unsigned wire representation to signed INTEGER32.
        if raw >= 2**31:
            raw -= 2**32

        # Read alarm status.
        alarm = read_sdo(bus, node, ALARM_INDEX, ALARM_SUBINDEX)

        sensor.raw_position = raw
        sensor.resolution_nm = resolution_nm
        sensor.position_mm = raw * resolution_nm / 1_000_000.0
        sensor.alarm = alarm
        sensor.updated_at = time.time()
        sensor.error = ""

    except (can.CanError, OSError, TimeoutError, RuntimeError, ValueError) as exc:
        sensor.error = str(exc)


def print_table(sensors, iteration):
    # ANSI terminal clear: works in typical Linux terminals.
    print("\033[2J\033[H", end="")
    print("TR-Electronic LMP 48 | CANopen SDO Monitor")
    print(f"Channel: {CHANNEL} | Nodes: 1-4 | Refresh: {REFRESH_INTERVAL:.2f}s")
    print("=" * 100)
    print(
        f"{'Node':<7}{'Position (mm)':>17}{'Raw position':>17}"
        f"{'Resolution (nm)':>20}{'Alarm':>12}  Status"
    )
    print("-" * 100)

    for s in sensors:
        if s.error:
            print(
                f"{s.node_id:<7}{'--':>17}{'--':>17}"
                f"{'--':>20}{'--':>12}  ERROR: {s.error}"
            )
        else:
            alarm_text = f"0x{s.alarm:X}"
            status = "ALARM" if s.alarm else "OK"
            print(
                f"{s.node_id:<7}{s.position_mm:>17.3f}"
                f"{s.raw_position:>17}{s.resolution_nm:>20}"
                f"{alarm_text:>12}  {status}"
            )

    print("=" * 100)
    print(f"Cycle: {iteration} | Press Ctrl+C to exit.")


def main():
    global CHANNEL, REFRESH_INTERVAL

    parser = argparse.ArgumentParser(
        description="Read four LMP 48 CANopen sensors using SDO."
    )
    parser.add_argument("--channel", default=CHANNEL, help="SocketCAN interface")
    parser.add_argument("--interval", type=float, default=REFRESH_INTERVAL,
                        help="Display refresh interval in seconds")
    args = parser.parse_args()

    CHANNEL = args.channel
    REFRESH_INTERVAL = max(0.1, args.interval)

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    sensors = [SensorData(node_id=n) for n in NODE_IDS]

    print(f"Opening {CHANNEL}...")
    try:
        with can.Bus(interface="socketcan", channel=CHANNEL) as bus:
            print("Connected. Reading nodes 1-4...")
            iteration = 0

            while running:
                iteration += 1
                cycle_start = time.monotonic()

                for sensor in sensors:
                    if not running:
                        break
                    read_sensor(bus, sensor)

                print_table(sensors, iteration)

                elapsed = time.monotonic() - cycle_start
                sleep_time = max(0, REFRESH_INTERVAL - elapsed)

                # Interruptible sleep.
                end = time.monotonic() + sleep_time
                while running and time.monotonic() < end:
                    time.sleep(min(0.02, end - time.monotonic()))

    except (can.CanError, OSError) as exc:
        print(f"\nCAN error: {exc}", file=sys.stderr)
        return 1

    print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

