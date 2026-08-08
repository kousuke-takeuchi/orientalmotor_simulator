#!/bin/bash
# vcan インターフェースを冪等に作成して up する。要 sudo。
set -eu
IFACE="${1:-vcan0}"

sudo modprobe vcan
if ! ip link show "$IFACE" >/dev/null 2>&1; then
    sudo ip link add dev "$IFACE" type vcan
fi
sudo ip link set up "$IFACE"
ip -o link show "$IFACE"
