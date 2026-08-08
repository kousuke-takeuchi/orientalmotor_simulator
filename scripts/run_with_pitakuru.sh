#!/bin/bash
# pitakuru の oriental_motor ノードと繋ぐための omsim 起動。
# pitakuru は can0 / node_id 1,2 / bitrate 500k / reduction 100 を前提にしている
# (src/pitakuru/config/motors/motors_oriental_motor.yaml)。
set -eu
CHANNEL="${1:-can0}"
RECORD="${2:-/tmp/omsim-pitakuru.jsonl}"

python3 -m omsim.apps.omsim_main \
    --channel "$CHANNEL" \
    --eds BLVD-KRD_CANopen_V200.eds \
    --node 1 \
    --node 2 \
    --record "$RECORD"
