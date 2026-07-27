#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace


MODULE_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(MODULE_DIR))
spec = importlib.util.spec_from_file_location("jk_bms_mqtt", MODULE_DIR / "jk_bms_mqtt.py")
jk_bms_mqtt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jk_bms_mqtt)


class FakeMqttClient:
    instances = []

    def __init__(self, *args, **kwargs):
        self.published = []
        self.closed = False
        FakeMqttClient.instances.append(self)

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))

    def close(self):
        self.closed = True


class JkBmsMqttTests(unittest.TestCase):
    def setUp(self):
        FakeMqttClient.instances = []

    def test_static_bms_payloads_are_cached_between_reads(self):
        calls = []

        def fake_read_payload(fd, address, command):
            calls.append(command)
            return {
                jk_bms_mqtt.COMMANDS["settings"]: b"settings",
                jk_bms_mqtt.COMMANDS["status"]: b"status",
                jk_bms_mqtt.COMMANDS["about"]: b"about",
            }[command]

        def fake_decode(status, settings, about):
            return {"status": status, "settings": settings, "about": about}

        cache = jk_bms_mqtt.BmsStaticCache(refresh_every=100)

        first = jk_bms_mqtt.read_bms_payloads_from_fd(
            1,
            0,
            static_cache=cache,
            read_payload_fn=fake_read_payload,
            decode_fn=fake_decode,
        )
        second = jk_bms_mqtt.read_bms_payloads_from_fd(
            1,
            0,
            static_cache=cache,
            read_payload_fn=fake_read_payload,
            decode_fn=fake_decode,
        )

        self.assertEqual(first, {"status": b"status", "settings": b"settings", "about": b"about"})
        self.assertEqual(second, {"status": b"status", "settings": b"settings", "about": b"about"})
        self.assertEqual(
            calls,
            [
                jk_bms_mqtt.COMMANDS["settings"],
                jk_bms_mqtt.COMMANDS["about"],
                jk_bms_mqtt.COMMANDS["status"],
                jk_bms_mqtt.COMMANDS["status"],
            ],
        )

    def test_static_bms_cache_refreshes_after_configured_interval(self):
        calls = []

        def fake_read_payload(fd, address, command):
            calls.append(command)
            return command

        cache = jk_bms_mqtt.BmsStaticCache(refresh_every=2)

        jk_bms_mqtt.read_bms_payloads_from_fd(1, 0, static_cache=cache, read_payload_fn=fake_read_payload, decode_fn=lambda *_: {})
        jk_bms_mqtt.read_bms_payloads_from_fd(1, 0, static_cache=cache, read_payload_fn=fake_read_payload, decode_fn=lambda *_: {})
        jk_bms_mqtt.read_bms_payloads_from_fd(1, 0, static_cache=cache, read_payload_fn=fake_read_payload, decode_fn=lambda *_: {})

        self.assertEqual(calls.count(jk_bms_mqtt.COMMANDS["settings"]), 2)
        self.assertEqual(calls.count(jk_bms_mqtt.COMMANDS["about"]), 2)
        self.assertEqual(calls.count(jk_bms_mqtt.COMMANDS["status"]), 3)

    def test_run_iteration_publishes_offline_when_bms_read_fails(self):
        args = SimpleNamespace(
            port="/dev/null",
            baud=115200,
            address=0,
            mqtt_host="core-mosquitto",
            mqtt_port=1883,
            mqtt_user="",
            mqtt_password="",
        )

        def failing_read_bms(port, baud, address):
            raise RuntimeError("No JK payload received")

        ok = jk_bms_mqtt.run_iteration(
            args,
            mqtt_client_cls=FakeMqttClient,
            read_bms_fn=failing_read_bms,
        )

        self.assertFalse(ok)
        self.assertEqual(len(FakeMqttClient.instances), 1)
        self.assertIn(("jk_bms/availability", "offline", True), FakeMqttClient.instances[0].published)
        self.assertTrue(FakeMqttClient.instances[0].closed)

    def test_run_iteration_publishes_state_and_online_when_bms_read_succeeds(self):
        args = SimpleNamespace(
            port="/dev/null",
            baud=115200,
            address=0,
            mqtt_host="core-mosquitto",
            mqtt_port=1883,
            mqtt_user="",
            mqtt_password="",
        )

        def successful_read_bms(port, baud, address):
            return {
                "model": "JK",
                "software_version": "1.0",
                "cell_count": 1,
                "cell_voltages_v": [3.31],
                "voltage_v": 53.0,
                "current_a": 1.5,
                "power_w": 79.5,
            }

        ok = jk_bms_mqtt.run_iteration(
            args,
            mqtt_client_cls=FakeMqttClient,
            read_bms_fn=successful_read_bms,
        )

        self.assertTrue(ok)
        published = FakeMqttClient.instances[0].published
        self.assertIn(("jk_bms/availability", "online", True), published)
        self.assertTrue(any(topic == "jk_bms/state" and payload["cell_01_v"] == 3.31 for topic, payload, _ in published))

    def test_bms_iteration_uses_configured_topic_prefix(self):
        bms = jk_bms_mqtt.BmsConfig(
            name="JK 24V 300Ah",
            topic_prefix="jk_24v300ah",
            port="/dev/null",
            baud=115200,
            address=0,
        )

        def successful_read_bms(port, baud, address, static_cache=None):
            return {
                "model": "JK",
                "software_version": "1.0",
                "cell_count": 1,
                "cell_voltages_v": [3.35],
                "voltage_v": 27.0,
                "current_a": 23.0,
                "power_w": 621.0,
            }

        ok = jk_bms_mqtt.run_bms_iteration(
            bms,
            mqtt_host="core-mosquitto",
            mqtt_port=1883,
            mqtt_user="jkbridge",
            mqtt_password="secret",
            mqtt_client_cls=FakeMqttClient,
            read_bms_fn=successful_read_bms,
        )

        self.assertTrue(ok)
        published = FakeMqttClient.instances[0].published
        self.assertIn(("jk_24v300ah/availability", "online", True), published)
        self.assertTrue(any(topic == "jk_24v300ah/state" and payload["cell_01_v"] == 3.35 for topic, payload, _ in published))
        self.assertTrue(any(topic == "homeassistant/sensor/jk_24v300ah/voltage_v/config" for topic, _, _ in published))
        self.assertFalse(any(topic.startswith("homeassistant/sensor/jk_bms/") for topic, _, _ in published))

    def test_polling_multiple_bms_keeps_failures_isolated(self):
        bms_configs = [
            jk_bms_mqtt.BmsConfig(
                name="JK 24V 180Ah",
                topic_prefix="jk_24v180ah",
                port="/dev/null",
                baud=115200,
                address=0,
            ),
            jk_bms_mqtt.BmsConfig(
                name="JK 24V 300Ah",
                topic_prefix="jk_24v300ah",
                port="/dev/zero",
                baud=115200,
                address=0,
            ),
        ]

        def mixed_read_bms(port, baud, address, static_cache=None):
            if port == "/dev/null":
                raise RuntimeError("No JK payload received")
            return {
                "model": "JK",
                "software_version": "1.0",
                "cell_count": 0,
                "cell_voltages_v": [],
                "voltage_v": 27.1,
                "current_a": 20.0,
                "power_w": 542.0,
            }

        results = jk_bms_mqtt.poll_bms_configs(
            bms_configs,
            mqtt_host="core-mosquitto",
            mqtt_port=1883,
            mqtt_user="jkbridge",
            mqtt_password="secret",
            mqtt_client_cls=FakeMqttClient,
            read_bms_fn=mixed_read_bms,
        )

        self.assertEqual(results, {"jk_24v180ah": False, "jk_24v300ah": True})
        all_published = [item for client in FakeMqttClient.instances for item in client.published]
        self.assertIn(("jk_24v180ah/availability", "offline", True), all_published)
        self.assertIn(("jk_24v300ah/availability", "online", True), all_published)
        self.assertTrue(any(topic == "jk_24v300ah/state" for topic, _, _ in all_published))

    def test_format_configured_bms_lines(self):
        options = {
            "bms": [
                {
                    "name": "JK 24V 180Ah",
                    "topic_prefix": "jk_24v180ah",
                    "serial_port": "/dev/serial/by-path/port-a",
                },
                {
                    "name": "JK 24V 300Ah",
                    "topic_prefix": "jk_24v300ah",
                    "serial_port": "/dev/serial/by-path/port-b",
                },
            ]
        }

        self.assertEqual(
            jk_bms_mqtt.format_configured_bms_lines(options),
            [
                "- JK 24V 180Ah: /dev/serial/by-path/port-a -> jk_24v180ah",
                "- JK 24V 300Ah: /dev/serial/by-path/port-b -> jk_24v300ah",
            ],
        )

    def test_options_mode_does_not_require_legacy_mqtt_host_argument(self):
        options = {
            "bms": [
                {
                    "name": "JK 24V 300Ah",
                    "topic_prefix": "jk_24v300ah",
                    "serial_port": "/dev/ttyUSB0",
                    "baud": 115200,
                    "address": 0,
                }
            ],
            "mqtt_host": "core-mosquitto",
            "mqtt_port": 1883,
            "mqtt_user": "",
            "mqtt_password": "",
            "interval": 10,
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as options_file:
            json.dump(options, options_file)
            options_file.flush()
            result = subprocess.run(
                [sys.executable, str(MODULE_DIR / "jk_bms_mqtt.py"), "--options", options_file.name, "--once"],
                cwd=MODULE_DIR,
                text=True,
                capture_output=True,
                timeout=5,
            )

        self.assertNotIn("the following arguments are required: --mqtt-host", result.stderr)

    def test_explicit_serial_path_does_not_fallback_to_another_adapter(self):
        with patch.object(jk_bms_mqtt.os.path, "exists", side_effect=lambda path: path == "/dev/serial/by-id/shared-adapter"):
            with patch.object(jk_bms_mqtt.glob, "glob", side_effect=lambda pattern: ["/dev/serial/by-id/shared-adapter"]):
                with self.assertRaises(FileNotFoundError):
                    jk_bms_mqtt.resolve_port("/dev/serial/by-path/missing-port")


if __name__ == "__main__":
    unittest.main()
