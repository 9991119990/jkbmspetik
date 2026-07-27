# JKBMS Petik Dual RS485 Design

## Goal

Build a separate Home Assistant add-on named `jkbmspetik` for Petik's HA that can read two JK BMS units over two independent USB-RS485 adapters without changing Roman's existing JK BMS add-on.

## Architecture

The add-on keeps the existing JK RS485 reader and MQTT publisher foundation, but changes the runtime configuration from one fixed BMS to a `bms` list. Each configured BMS has its own serial port, baud rate, address, display name, and MQTT topic prefix.

The publisher uses each `topic_prefix` for MQTT state, availability, and Home Assistant discovery IDs. That prevents both BMS units from overwriting the same `jk_bms/...` topics or Home Assistant entities.

## Configuration

The add-on accepts:

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

## Data Flow

Every interval, the add-on loops through the configured BMS list serially. One failed BMS read publishes only that BMS as offline and does not block the other BMS from being read and published.

For `topic_prefix: jk_24v300ah`, topics are:

- `jk_24v300ah/state`
- `jk_24v300ah/availability`
- `homeassistant/sensor/jk_24v300ah/<key>/config`
- `homeassistant/binary_sensor/jk_24v300ah/<key>/config`

## Error Handling

Each BMS gets its own static cache and availability topic. An `OSError` clears only that BMS cache. The log prints the configured BMS name with success and failure messages.

## Testing

Tests cover:

- discovery config uses topic-prefixed unique IDs and availability topics
- one BMS iteration publishes state and availability to the configured prefix
- multiple BMS polling keeps failures isolated and continues to the next BMS
