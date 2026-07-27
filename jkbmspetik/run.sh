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
python3 - <<'PY'
import json
from jk_bms_mqtt import format_configured_bms_lines

with open("/data/options.json", encoding="utf-8") as options_file:
    for line in format_configured_bms_lines(json.load(options_file)):
        print(line)
PY

exec python3 /app/jk_bms_mqtt.py \
  --options "${CONFIG}"
