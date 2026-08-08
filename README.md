# オリエンタルモーター BLVD-KRD CANopen シミュレータ

実機のモーター・ドライバなしに、BLVD-KRD ドライバの CANopen 通信を PC 上で再現します。
複数台（右/左モーター）を 1 本の CAN バス上で同時にシミュレートできます。

- 設計書: `docs/superpowers/specs/2026-08-08-oriental-motor-simulator-design.md`
- 仕様の正本: `docs/oriental_motor/HP-5143E.pdf`（CANopen）、`docs/oriental_motor/HP-5141J.pdf`（機能編）

## セットアップ（Vagrant VM）

前提: `pitakuru_ws/src/Vagrantfile` に本リポジトリの synced_folder 設定
（`/home/vagrant/KEISUU/omsim` にマウント）が入っていること。

```bash
cd /c/Users/ktake/code/pitakuru_ws/src
vagrant reload
vagrant ssh -c "bash /home/vagrant/KEISUU/omsim/scripts/vagrant_provision.sh"
```

`scripts/vagrant_provision.sh` が行うこと:
- `python3-pip` / `can-utils` の apt インストール
- `requirements.txt` からの依存導入（`canopen` / `python-can` / `pytest` / `PyYAML`）
- `pip install --user -e .` による omsim 本体の editable インストール
- `omsim-vcan.service` の systemd 登録・有効化（VM 再起動後も `vcan0` を自動復旧）
- 検証用の `ip -o link show vcan0` / `python3 -m pytest --version` / `python3 -c "import omsim..."` 出力

期待される最終出力:
```
4: vcan0: <NOARP,UP,LOWER_UP> mtu 72 ...
pytest 8.3.5
omsim 0.1.0
```

## 起動

```bash
omsim --channel vcan0 --node 1 --node 2
```

## テスト

VM 上で直接:

```bash
cd /home/vagrant/KEISUU/omsim
python3 -m pytest -q
```

Windows 側から VM のテストを走らせる（リポジトリ直下に `.vm-ssh-config` を用意した上で）:

```bash
ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q"
```

`.vm-ssh-config` は各自で生成する（gitignore 済みなのでコミットしない）:

```bash
cd /c/Users/ktake/code/pitakuru_ws/src
vagrant ssh-config > /c/Users/ktake/code/keisuu/oriental_motor_simulator/.vm-ssh-config
```

期待結果: `75 passed`（SKIP 0 件。`vcan0` が上がっているので integration テストも実行される）

## シナリオ実行

```bash
omsim-scenario tests/scenarios/sdo_smoke.yaml --junit junit.xml
```

## トラブルシューティング

- **`chmod +x` が効かない**: VirtualBox の共有フォルダ（vboxsf）上ではファイルモードの変更が反映されない。
  実行ビットは Windows 側のリポジトリで `git update-index --chmod=+x <file>` を実行して立てる。
- **VM を再起動すると `vcan0` が消える**: `vcan0` は永続デバイスではないため。
  `omsim-vcan.service` を `systemctl enable` していれば起動時に自動で再作成される
  （`vagrant_provision.sh` が enable まで行う）。
- **`python3 -m pytest --version` が 8.3.5 でない**: Ubuntu 20.04 には pytest 4.6.9 が同梱されており、
  PATH の解決順によってはそちらが優先されてしまうことがある。
  `python3 -m pip install --user -r requirements.txt` を実行し直し、
  `python3 -m pytest --version` で 8.3.5 になっていることを確認する。
