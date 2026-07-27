#!/usr/bin/env python3
import argparse
import json
import os
import select
import struct
import termios
import time


BAUDS = {
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    115200: termios.B115200,
}

COMMANDS = {
    "status": bytes.fromhex("10 16 20 00 01 02 00 00"),
    "settings": bytes.fromhex("10 16 1e 00 01 02 00 00"),
    "about": bytes.fromhex("10 16 1c 00 01 02 00 00"),
}


def crc16_modbus(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc >> 1) ^ 0xA001) if crc & 1 else (crc >> 1)
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def configure_port(fd: int, baud: int) -> None:
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0
    attrs[4] = BAUDS[baud]
    attrs[5] = BAUDS[baud]
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 1
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIOFLUSH)


def exchange(fd: int, frame: bytes, timeout: float = 1.4) -> bytes:
    termios.tcflush(fd, termios.TCIOFLUSH)
    time.sleep(0.15)
    os.write(fd, frame)
    deadline = time.time() + timeout
    data = b""
    while time.time() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.02)
        if readable:
            chunk = os.read(fd, 2048)
            if chunk:
                data += chunk
                deadline = time.time() + 0.15
    return data


def read_payload(fd: int, address: int, command: bytes) -> bytes:
    frame = bytes([address]) + command + crc16_modbus(bytes([address]) + command)
    last_raw = b""
    for _ in range(3):
        raw = exchange(fd, frame)
        last_raw = raw
        start = raw.find(b"\x55\xaa")
        if start >= 0 and len(raw) >= start + 300:
            payload = raw[start : start + 300]
            checksum = sum(payload[:299]) & 0xFF
            if checksum != payload[299]:
                raise RuntimeError(
                    f"Checksum mismatch: computed={checksum:02x} received={payload[299]:02x}"
                )
            return payload
        time.sleep(0.3)
    raise RuntimeError(f"No JK payload received, raw={last_raw.hex(' ')}")


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def i16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<h", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def i32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def text(data: bytes, offset: int, length: int) -> str:
    return data[offset : offset + length].decode("utf-8", "ignore").split("\x00", 1)[0]


def decode(status: bytes, settings: bytes, about: bytes) -> dict:
    cell_count = i32(settings, 114)
    cells = [round(u16(status, 6 + i * 2) / 1000, 3) for i in range(cell_count)]
    voltage = u32(status, 150) / 1000
    current = i32(status, 158) / 1000
    min_cell = min(cells) if cells else None
    max_cell = max(cells) if cells else None
    return {
        "model": text(about, 6, 16),
        "hardware_version": text(about, 22, 8),
        "software_version": text(about, 30, 8),
        "serial": text(about, 46, 16),
        "pin": text(about, 118, 16),
        "voltage_v": round(voltage, 3),
        "current_a": round(current, 3),
        "power_w": round(voltage * current, 1),
        "soc_percent": status[173],
        "soh_percent": status[190],
        "remaining_capacity_ah": round(i32(status, 174) / 1000, 3),
        "nominal_capacity_ah": round(i32(settings, 130) / 1000, 3),
        "cycles": i32(status, 182),
        "cell_count": cell_count,
        "cell_voltages_v": cells,
        "min_cell_v": min_cell,
        "max_cell_v": max_cell,
        "delta_cell_mv": round((max_cell - min_cell) * 1000) if cells else None,
        "mos_temp_c": round(i16(status, 144) / 10, 1),
        "temp1_c": round(i16(status, 162) / 10, 1),
        "temp2_c": round(i16(status, 164) / 10, 1),
        "temp3_c": round(i16(status, 256) / 10, 1),
        "temp4_c": round(i16(status, 258) / 10, 1),
        "balancing": bool(status[172]),
        "charge_fet": bool(status[198]),
        "discharge_fet": bool(status[199]),
        "heating": bool(status[215]),
        "max_charge_current_a": round(i32(settings, 50) / 1000, 3),
        "max_discharge_current_a": round(i32(settings, 62) / 1000, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200, choices=sorted(BAUDS))
    parser.add_argument("--address", type=lambda value: int(value, 0), default=0)
    args = parser.parse_args()

    with open(args.port, "rb+", buffering=0) as port:
        fd = port.fileno()
        configure_port(fd, args.baud)
        settings = read_payload(fd, args.address, COMMANDS["settings"])
        status = read_payload(fd, args.address, COMMANDS["status"])
        about = read_payload(fd, args.address, COMMANDS["about"])

    print(json.dumps(decode(status, settings, about), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
