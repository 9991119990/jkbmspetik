# JKBMS Petik

Home Assistant add-on repository for reading two JK BMS units over two separate USB-RS485 adapters.

This project is separate from Roman's existing JK BMS add-on. It publishes each BMS to its own MQTT topic prefix so Home Assistant entities do not overwrite each other.

## Add-on

The add-on lives in:

```text
jkbmspetik/
```

Default Petik configuration:

```yaml
bms:
  - name: "JK 24V 180Ah"
    topic_prefix: "jk_24v180ah"
    serial_port: >-
      /dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.4:1.0-port0
    baud: 115200
    address: 0

  - name: "JK 24V 300Ah"
    topic_prefix: "jk_24v300ah"
    serial_port: >-
      /dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.1:1.0-port0
    baud: 115200
    address: 0

mqtt_host: core-mosquitto
mqtt_port: 1883
mqtt_user: jkbridge
mqtt_password: "doplnit_mqtt_heslo"
interval: 10
```

## MQTT Topics

The add-on publishes:

```text
jk_24v180ah/state
jk_24v180ah/availability
jk_24v300ah/state
jk_24v300ah/availability
```

MQTT discovery creates separate Home Assistant entities such as:

```text
sensor.jk_24v180ah_voltage
sensor.jk_24v300ah_voltage
```

## USB Paths

Petik has two identical `1a86:7523` USB serial adapters. Do not use `/dev/serial/by-id/` for them because only one shared by-id entry appears. Use `/dev/serial/by-path/` so each add-on port follows the physical USB port.
