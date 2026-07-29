#!/usr/bin/env python3
import argparse
from dataclasses import dataclass
import glob
import json
import os
import socket
import statistics
import time

from read_jk_bms import COMMANDS, configure_port, decode, read_payload


SENSORS = [
    ("voltage_v", "Voltage", "V", "voltage"),
    ("current_a", "Current", "A", "current"),
    ("power_w", "Power", "W", "power"),
    ("soc_percent", "SOC", "%", "battery"),
    ("soh_percent", "SOH", "%", None),
    ("remaining_capacity_ah", "Remaining capacity", "Ah", None),
    ("nominal_capacity_ah", "Nominal capacity", "Ah", None),
    ("cycles", "Cycles", None, None),
    ("delta_cell_mv", "Cell delta", "mV", "voltage"),
    ("cell_voltage_min_v", "Cell voltage min", "V", "voltage"),
    ("cell_voltage_max_v", "Cell voltage max", "V", "voltage"),
    ("cell_voltage_average_v", "Cell voltage average", "V", "voltage"),
    ("cell_voltage_median_v", "Cell voltage median", "V", "voltage"),
    ("cell_voltage_delta_v", "Cell voltage delta", "V", "voltage"),
    ("mos_temp_c", "MOS temperature", "°C", "temperature"),
    ("temp1_c", "Temperature 1", "°C", "temperature"),
    ("temp2_c", "Temperature 2", "°C", "temperature"),
    ("max_charge_current_a", "Max charge current", "A", "current"),
    ("max_discharge_current_a", "Max discharge current", "A", "current"),
]

BINARY_SENSORS = [
    ("balancing", "Balancing"),
    ("charge_fet", "Charge FET"),
    ("discharge_fet", "Discharge FET"),
    ("heating", "Heating"),
]


@dataclass(frozen=True)
class BmsConfig:
    name: str
    topic_prefix: str
    port: str
    baud: int
    address: int


class BmsStaticCache:
    def __init__(self, refresh_every=120):
        self.refresh_every = max(1, int(refresh_every))
        self.settings = None
        self.about = None
        self.reads = 0

    def should_refresh(self) -> bool:
        return self.settings is None or self.about is None or self.reads >= self.refresh_every

    def update(self, settings: bytes, about: bytes) -> None:
        self.settings = settings
        self.about = about
        self.reads = 0

    def mark_status_read(self) -> None:
        self.reads += 1

    def clear(self) -> None:
        self.settings = None
        self.about = None
        self.reads = 0


def enc_str(value: str) -> bytes:
    data = value.encode()
    return len(data).to_bytes(2, "big") + data


def enc_len(length: int) -> bytes:
    out = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length:
            digit |= 0x80
        out.append(digit)
        if not length:
            return bytes(out)


class MqttClient:
    def __init__(self, host, port, username=None, password=None, client_id="jk-bms-rs485"):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.username = username
        self.password = password
        self.client_id = client_id
        self._connect()

    def _send(self, packet_type: int, flags: int, payload: bytes) -> None:
        self.sock.sendall(bytes([(packet_type << 4) | flags]) + enc_len(len(payload)) + payload)

    def _connect(self) -> None:
        flags = 0x02
        payload = enc_str(self.client_id)
        if self.username is not None:
            flags |= 0x80
            payload += enc_str(self.username)
        if self.password is not None:
            flags |= 0x40
            payload += enc_str(self.password)
        variable = enc_str("MQTT") + bytes([4, flags, 0, 60])
        self._send(1, 0, variable + payload)
        response = self.sock.recv(4)
        if len(response) < 4 or response[0] != 0x20 or response[3] != 0:
            raise RuntimeError(f"MQTT connect failed: {response.hex(' ')}")

    def publish(self, topic: str, payload, retain=False) -> None:
        if not isinstance(payload, str):
            payload = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        flags = 0x01 if retain else 0x00
        self._send(3, flags, enc_str(topic) + payload.encode())

    def close(self) -> None:
        try:
            self._send(14, 0, b"")
        finally:
            self.sock.close()


def read_bms_payloads_from_fd(fd: int, address: int, static_cache=None, read_payload_fn=read_payload, decode_fn=decode) -> dict:
    if static_cache is None:
        settings = read_payload_fn(fd, address, COMMANDS["settings"])
        status = read_payload_fn(fd, address, COMMANDS["status"])
        about = read_payload_fn(fd, address, COMMANDS["about"])
        return decode_fn(status, settings, about)

    if static_cache.should_refresh():
        settings = read_payload_fn(fd, address, COMMANDS["settings"])
        about = read_payload_fn(fd, address, COMMANDS["about"])
        static_cache.update(settings, about)

    status = read_payload_fn(fd, address, COMMANDS["status"])
    static_cache.mark_status_read()
    return decode_fn(status, static_cache.settings, static_cache.about)


def read_bms(port: str, baud: int, address: int, static_cache=None) -> dict:
    with open(port, "rb+", buffering=0) as serial_port:
        fd = serial_port.fileno()
        configure_port(fd, baud)
        return read_bms_payloads_from_fd(fd, address, static_cache=static_cache)


def resolve_port(configured_port: str) -> str:
    strict_prefixes = (
        "/dev/serial/by-path/",
        "/dev/serial/by-id/",
        "/dev/ttyUSB",
        "/dev/ttyACM",
    )
    if configured_port.startswith(strict_prefixes):
        if os.path.exists(configured_port):
            return configured_port
        raise FileNotFoundError(f"Configured serial port is not available: {configured_port}")

    candidates = [configured_port, "/dev/ttyACM0"]
    candidates.extend(sorted(glob.glob("/dev/serial/by-id/*")))
    candidates.extend(sorted(glob.glob("/dev/ttyACM*")))
    candidates.extend(sorted(glob.glob("/dev/ttyUSB*")))

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if os.path.exists(candidate):
            if candidate != configured_port:
                print(f"Configured serial port {configured_port} is not available, using {candidate}", flush=True)
            return candidate
    return configured_port


def discovery_config(
    name,
    key,
    state_topic,
    device,
    availability_topic="jk_bms/availability",
    unique_id_prefix="jk_bms",
    unit=None,
    device_class=None,
    binary=False,
    suggested_display_precision=None,
):
    cfg = {
        "name": name,
        "unique_id": f"{unique_id_prefix}_{key}",
        "state_topic": state_topic,
        "availability_topic": availability_topic,
        "device": device,
    }
    if binary:
        cfg["payload_on"] = "true"
        cfg["payload_off"] = "false"
        cfg["value_template"] = "{{ value_json." + key + " | lower }}"
    else:
        cfg["value_template"] = "{{ value_json." + key + " }}"
        if unit:
            cfg["unit_of_measurement"] = unit
        if device_class:
            cfg["device_class"] = device_class
        if suggested_display_precision is not None:
            cfg["suggested_display_precision"] = suggested_display_precision
        if key.endswith("_v") or key.endswith("_a") or key.endswith("_w") or key.endswith("_c"):
            cfg["state_class"] = "measurement"
    return cfg


def publish_discovery(
    client: MqttClient,
    state_topic: str,
    sample: dict,
    topic_prefix="jk_bms",
    device_name="JK BMS RS485",
) -> None:
    availability_topic = f"{topic_prefix}/availability"
    device = {
        "identifiers": [f"{topic_prefix}_rs485"],
        "name": device_name,
        "manufacturer": "Jikong",
        "model": sample.get("model"),
        "sw_version": sample.get("software_version"),
    }
    for key, name, unit, device_class in SENSORS:
        topic = f"homeassistant/sensor/{topic_prefix}/{key}/config"
        precision = 3 if key.endswith("_v") else None
        client.publish(
            topic,
            discovery_config(
                name,
                key,
                state_topic,
                device,
                availability_topic=availability_topic,
                unique_id_prefix=topic_prefix,
                unit=unit,
                device_class=device_class,
                suggested_display_precision=precision,
            ),
            retain=True,
        )
    for key, name in BINARY_SENSORS:
        topic = f"homeassistant/binary_sensor/{topic_prefix}/{key}/config"
        client.publish(
            topic,
            discovery_config(
                name,
                key,
                state_topic,
                device,
                availability_topic=availability_topic,
                unique_id_prefix=topic_prefix,
                binary=True,
            ),
            retain=True,
        )
    for idx in range(1, int(sample.get("cell_count", 0)) + 1):
        key = f"cell_{idx:02d}_v"
        topic = f"homeassistant/sensor/{topic_prefix}/{key}/config"
        cfg = discovery_config(
            f"Cell {idx:02d}",
            key,
            state_topic,
            device,
            availability_topic=availability_topic,
            unique_id_prefix=topic_prefix,
            unit="V",
            device_class="voltage",
            suggested_display_precision=3,
        )
        client.publish(topic, cfg, retain=True)


def flatten_cells(data: dict) -> dict:
    out = dict(data)
    cells = data.get("cell_voltages_v", [])
    for idx, voltage in enumerate(cells, 1):
        out[f"cell_{idx:02d}_v"] = voltage
    if cells:
        out["cell_voltage_min_v"] = round(min(cells), 3)
        out["cell_voltage_max_v"] = round(max(cells), 3)
        out["cell_voltage_average_v"] = round(sum(cells) / len(cells), 3)
        out["cell_voltage_median_v"] = round(statistics.median(cells), 3)
        out["cell_voltage_delta_v"] = round(max(cells) - min(cells), 3)
    return out


def publish_availability(args, payload: str, mqtt_client_cls=MqttClient) -> bool:
    return publish_availability_to_topic(
        args.mqtt_host,
        args.mqtt_port,
        args.mqtt_user or None,
        args.mqtt_password or None,
        "jk_bms/availability",
        payload,
        mqtt_client_cls,
    )


def publish_availability_to_topic(host, port, username, password, topic: str, payload: str, mqtt_client_cls=MqttClient) -> bool:
    client = None
    try:
        client = mqtt_client_cls(host, port, username, password)
        client.publish(topic, payload, retain=True)
        return True
    except Exception as exc:
        print(f"MQTT availability publish failed: {exc}", flush=True)
        return False
    finally:
        if client is not None:
            client.close()


def run_bms_iteration(
    bms: BmsConfig,
    mqtt_host,
    mqtt_port,
    mqtt_user=None,
    mqtt_password=None,
    mqtt_client_cls=MqttClient,
    read_bms_fn=read_bms,
    static_cache=None,
) -> bool:
    state_topic = f"{bms.topic_prefix}/state"
    availability_topic = f"{bms.topic_prefix}/availability"
    client = None
    try:
        port = resolve_port(bms.port)
        if static_cache is None:
            data = flatten_cells(read_bms_fn(port, bms.baud, bms.address))
        else:
            data = flatten_cells(read_bms_fn(port, bms.baud, bms.address, static_cache=static_cache))
        client = mqtt_client_cls(mqtt_host, mqtt_port, mqtt_user or None, mqtt_password or None)
        publish_discovery(client, state_topic, data, topic_prefix=bms.topic_prefix, device_name=bms.name)
        client.publish(availability_topic, "online", retain=True)
        client.publish(state_topic, data, retain=False)
        print(
            f"Published {bms.name}: {data.get('voltage_v')}V "
            f"{data.get('current_a')}A SOC={data.get('soc_percent')}%",
            flush=True,
        )
        return True
    except Exception as exc:
        print(f"{bms.name} read/publish failed: {exc}", flush=True)
        if isinstance(exc, OSError) and static_cache is not None:
            static_cache.clear()
        if client is not None:
            try:
                client.publish(availability_topic, "offline", retain=True)
            except Exception as mqtt_exc:
                print(f"{bms.name} MQTT availability publish failed: {mqtt_exc}", flush=True)
        else:
            publish_availability_to_topic(
                mqtt_host,
                mqtt_port,
                mqtt_user or None,
                mqtt_password or None,
                availability_topic,
                "offline",
                mqtt_client_cls,
            )
        return False
    finally:
        if client is not None:
            client.close()


def poll_bms_configs(
    bms_configs,
    mqtt_host,
    mqtt_port,
    mqtt_user=None,
    mqtt_password=None,
    mqtt_client_cls=MqttClient,
    read_bms_fn=read_bms,
    static_caches=None,
) -> dict:
    if static_caches is None:
        static_caches = {}
    results = {}
    for bms in bms_configs:
        cache = static_caches.get(bms.topic_prefix)
        results[bms.topic_prefix] = run_bms_iteration(
            bms,
            mqtt_host,
            mqtt_port,
            mqtt_user=mqtt_user,
            mqtt_password=mqtt_password,
            mqtt_client_cls=mqtt_client_cls,
            read_bms_fn=read_bms_fn,
            static_cache=cache,
        )
    return results


def run_iteration(args, mqtt_client_cls=MqttClient, read_bms_fn=read_bms, static_cache=None) -> bool:
    state_topic = "jk_bms/state"
    client = None
    try:
        port = resolve_port(args.port)
        if static_cache is None:
            data = flatten_cells(read_bms_fn(port, args.baud, args.address))
        else:
            data = flatten_cells(read_bms_fn(port, args.baud, args.address, static_cache=static_cache))
        client = mqtt_client_cls(args.mqtt_host, args.mqtt_port, args.mqtt_user or None, args.mqtt_password or None)
        publish_discovery(client, state_topic, data)
        client.publish("jk_bms/availability", "online", retain=True)
        client.publish(state_topic, data, retain=False)
        print(
            f"Published JK BMS data: {data.get('voltage_v')}V "
            f"{data.get('current_a')}A SOC={data.get('soc_percent')}%",
            flush=True,
        )
        return True
    except Exception as exc:
        print(f"Read/publish failed: {exc}", flush=True)
        if isinstance(exc, OSError) and static_cache is not None:
            static_cache.clear()
        if client is not None:
            try:
                client.publish("jk_bms/availability", "offline", retain=True)
            except Exception as mqtt_exc:
                print(f"MQTT availability publish failed: {mqtt_exc}", flush=True)
        else:
            publish_availability(args, "offline", mqtt_client_cls)
        return False
    finally:
        if client is not None:
            client.close()


def parse_bms_configs(options: dict) -> list[BmsConfig]:
    raw_bms = options.get("bms") or []
    if raw_bms:
        return [
            BmsConfig(
                name=str(item["name"]),
                topic_prefix=str(item["topic_prefix"]),
                port=str(item["serial_port"]),
                baud=int(item.get("baud", 115200)),
                address=int(item.get("address", 0)),
            )
            for item in raw_bms
        ]
    return [
        BmsConfig(
            name="JK BMS RS485",
            topic_prefix="jk_bms",
            port=str(options.get("serial_port", options.get("port", "/dev/ttyACM0"))),
            baud=int(options.get("baud", 115200)),
            address=int(options.get("address", 0)),
        )
    ]


def format_configured_bms_lines(options: dict) -> list[str]:
    return [
        f"- {item['name']}: {item['serial_port']} -> {item['topic_prefix']}"
        for item in options.get("bms", [])
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--address", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--mqtt-host")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-user")
    parser.add_argument("--mqtt-password")
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--options")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if args.options:
        with open(args.options, encoding="utf-8") as options_file:
            options = json.load(options_file)
        bms_configs = parse_bms_configs(options)
        mqtt_host = options["mqtt_host"]
        mqtt_port = int(options.get("mqtt_port", 1883))
        mqtt_user = options.get("mqtt_user", "")
        mqtt_password = options.get("mqtt_password", "")
        interval = float(options.get("interval", 10))
        static_caches = {
            bms.topic_prefix: BmsStaticCache(refresh_every=max(12, round(600 / max(interval, 1))))
            for bms in bms_configs
        }
        while True:
            poll_bms_configs(
                bms_configs,
                mqtt_host,
                mqtt_port,
                mqtt_user=mqtt_user,
                mqtt_password=mqtt_password,
                static_caches=static_caches,
            )
            if args.once:
                break
            time.sleep(interval)
        return

    if not args.mqtt_host:
        parser.error("the following arguments are required in legacy mode: --mqtt-host")

    static_cache = BmsStaticCache(refresh_every=max(12, round(600 / max(args.interval, 1))))

    while True:
        run_iteration(args, static_cache=static_cache)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
