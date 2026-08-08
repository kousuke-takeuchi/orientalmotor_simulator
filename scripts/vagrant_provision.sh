#!/bin/bash
# Vagrant VM (Ubuntu 20.04 / Python 3.8) に omsim をセットアップする。
set -eu
REPO="${1:-/home/vagrant/KEISUU/omsim}"

sudo apt-get update
sudo apt-get install -y python3-pip can-utils

# Ubuntu 20.04 には pytest 4.6.9 が同梱されており、それが優先されることがある。
# requirements.txt から必ず入れ、バージョンを実測で確認する。
python3 -m pip install --user -r "$REPO/requirements.txt"
python3 -m pip install --user -e "$REPO"

sudo install -m 0644 "$REPO/scripts/omsim-vcan.service" /etc/systemd/system/omsim-vcan.service
sudo systemctl daemon-reload
sudo systemctl enable --now omsim-vcan.service

ip -o link show vcan0
python3 -m pytest --version
python3 -c "import omsim; print('omsim', omsim.__version__)"
