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

# コンソールスクリプト導入の確認と PATH の注意
echo ""
echo "=== コンソールスクリプトの確認 ==="
ls -1 "$HOME/.local/bin/omsim" "$HOME/.local/bin/omsim-scenario"
echo "✓ コンソールスクリプト omsim / omsim-scenario が ~/.local/bin にインストールされました"
echo ""
echo "重要: ~/.local/bin が PATH に含まれていない場合は、以下のいずれかを実行してください:"
echo "  • 一度ログアウト・再ログインする"
echo "  • または source ~/.profile を実行する"
echo ""
echo "非ログインシェル(ssh host \"コマンド\" など)では python3 -m 形式を使用してください:"
echo "  python3 -m omsim.apps.omsim_main --channel vcan0 --node 1 --node 2"
