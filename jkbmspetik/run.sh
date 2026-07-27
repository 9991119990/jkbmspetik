#!/usr/bin/with-contenv sh
set -eu

CONFIG=/data/options.json

mqtt_host=$(python3 -c 'import json; print(json.load(open("/data/options.json"))["mqtt_host"])')
mqtt_port=$(python3 -c 'import json; print(json.load(open("/data/options.json"))["mqtt_port"])')
interval=$(python3 -c 'import json; print(json.load(open("/data/options.json"))["interval"])')

echo "Starting JKBMS Petik RS485 MQTT bridge"
echo "MQTT broker: ${mqtt_host}:${mqtt_port}"
echo "Interval: ${interval}s"
echo "Configured BMS devices:"
python3 -c 'import json; [print(f"- {bms[\"name\"]}: {bms[\"serial_port\"]} -> {bms[\"topic_prefix\"]}") for bms in json.load(open("/data/options.json")).get("bms", [])]'

exec python3 /app/jk_bms_mqtt.py \
  --options "${CONFIG}"
