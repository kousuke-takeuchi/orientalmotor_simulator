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
- `requirements.txt` からの依存導入（`canopen` / `python-can` / `pytest` / `PyYAML` / `fastapi` / `uvicorn` / `httpx` / `websockets`）
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

### コンソールスクリプトを使う（推奨）

`pip install --user -e .` により、コンソールスクリプト `omsim` および `omsim-scenario` が `~/.local/bin` にインストールされます。

**ログインシェルから実行する場合（通常の利用）:**
```bash
omsim --channel vcan0 --node 1 --node 2
```

**注意事項:**
- `vagrant ssh` で VM にログインした場合は、上記のコマンドが直接使えます。
- **プロビジョニング直後の同一セッションでは PATH に `~/.local/bin` が反映されていない可能性があります。**
  その場合は以下のいずれかを実行してください:
  - 一度 `exit` で SSH を切断してから `vagrant ssh` で再ログインする
  - または、`source ~/.profile` を実行して PATH を再読み込みする

### Python モジュール形式（常に動く・CI/CD 向け）

非ログインシェル環境（`ssh host "コマンド"` 形式や自動化スクリプト）では、次の形式を使ってください:

```bash
python3 -m omsim.apps.omsim_main --channel vcan0 --node 1 --node 2
```

シナリオ実行の場合:
```bash
python3 -m omsim.apps.scenario tests/scenarios/sdo_smoke.yaml --junit junit.xml
```

この方法は PATH の影響を受けず、どの環境でも確実に動作します。

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

期待結果: `264 passed`（SKIP 0 件。`vcan0` が上がっているので integration テストも実行される）

**既知の flaky テスト**: `tests/integration/` 配下の vcan 経由 SDO テスト（例:
`test_scenario_run.py::test_smoke_scenario_all_steps_pass`、
`test_sdo_over_vcan.py::test_reads_device_name_over_vcan`）は、稀に
`SdoCommunicationError: Unexpected response 0x41` で落ちることがある。
3 回連続実行したところ、落ちるテストがそのたびに変わり（毎回同じテストではない）、
再実行すると通ることを確認済み。vcan0 のタイミング起因の不安定さであり、
シミュレータ本体の不具合ではないと考えられる。落ちた場合は再実行すること。

## Web モニタ

`--web-port` を付けて起動すると、シミュレーション状態をブラウザからリアルタイムに確認できます。
（設計書 4.1 の通り、Web は無くてもシミュレーションは完全に動きます。`--web-port` を付けない限り
Web サーバは一切起動しません＝ヘッドレス実行そのままです。）

```bash
python3 -m omsim.apps.omsim_main --node 1 --node 2 --web-port 8080
```

VM 上で実行した場合、ブラウザで VM の IP（例: `http://192.168.33.10:8080/`）を開くと 3 ペインが表示されます。

- **ステータスモニタ**: 各ノードの状態（NMT ステート、Statusword、動作モード等）を一覧表示
- **波形モニタ**: 速度・位置など時系列の値をグラフで表示。シナリオ実行中は波形がリアルタイムに動く
- **CAN フレームログ**: バス上を流れる CAN フレームを時系列で表示

CAN フレームログには、受信フレームだけでなく omsim 自身の送信フレーム
（SDO レスポンス / boot-up / Heartbeat / EMCY / TPDO / SYNC / node guarding 応答）も
`tx` として出ます。`python-can` の `receive_own_messages` は既定で無効ですが、
送信経路（`network.bus.send`）を 1 箇所だけラップして記録しているためです（P3 で対応）。

`--web-host` でバインドアドレスを指定できます。既定は `127.0.0.1`（ローカルのみ）なので、
VM の外のブラウザから開く場合は明示的に `--web-host 0.0.0.0` を指定してください。

## PDO / SYNC / エラー制御（P3）

- **PDO**: RPDO 4 本（`1400h`-`1403h` 通信パラメータ / `1600h`-`1603h` マッピング）と
  TPDO 4 本（`1800h`-`1803h` / `1A00h`-`1A03h`）。マッピングは動的に変更できます。
  変更手順は仕様どおり「PDO を bit31=1 で無効化 → マッピング sub0 を 0 → sub1-4 を書換
  → sub0 に個数 → PDO を bit31=0 で再有効化」です。
  transmission type は RPDO が `00h`/`FEh`/`FFh`、TPDO が `00h`（変化時に次の SYNC で送信）/
  `01h`-`F0h`（n 回目の SYNC ごと）/`FCh`/`FDh`/`FEh`/`FFh`（inhibit time・event timer 駆動）。
  予約値（`F1h`-`FBh`）への変更は SDO abort `06090030h` で拒否します。
- **SYNC**: `1005h` の bit30 を立てると omsim 自身が SYNC producer になります。
  周期は `1006h`（μs 単位、0-1,000,000）。bit30 を立てなければ consumer としてのみ動作します。
- **Heartbeat consumer**: `1016h` sub1 に `(node_id<<16)|time_ms` を書くと、そのノードの
  Heartbeat が時間内に来なければ EMCY `8130h`（node guarding / heartbeat error）を発行します。
- **node guarding**: `100Ch`（guard time, ms）/`100Dh`（life time factor）の値を保持し、
  `700h+NodeID` への RTR に `(toggle<<7)|NMT状態コード` の 1 バイトで応答します。
  生死判定そのものは NMT マスタの責務のため omsim 側では行いません。
- **1003h**: CiA301 の Pre-defined error field 形式（下位 16bit = EMCY コード、
  上位 16bit = メーカ固有コード）。まだ記録の無い sub を読むと abort `08000024h` を返します。

**既知の制限**

- PDO マッピングはバイト境界のみ対応（ビット単位のサブバイトパッキングは対象外）。
  EDS の既定マッピングが全てバイト境界のため、この範囲で十分と判断しています。
- SYNC 受信の検出粒度はシミュレーションステップと同じ 1ms。1ms 未満に複数届いた SYNC は 1 回として扱います。
- PDO パラメータの NMT 状態によるアクセス制御は行いません（Pre-operational で設定する運用前提）。

## 網羅率の確認

EDS（オブジェクト辞書）に定義されたオブジェクトのうち、どこまで実装済みかを確認できます。

```bash
python3 -m omsim.apps.omsim_main --coverage
```

実装済み・値の保持のみ・未実装の件数と、未実装オブジェクトの一覧（インデックス:サブインデックス）が出力されます。

## 未実装スタブの確認

「値の保持のみ」など、部分的にしか実装されていないオブジェクトの一覧と、その理由・対応予定フェーズを確認できます。

```bash
python3 -m omsim.apps.omsim_main --list-stubs
```

各行はオブジェクトのインデックス:サブインデックスと、対応予定フェーズ（P3 以降）を含む説明です。

## シナリオ実行

**コンソールスクリプト形式:**
```bash
omsim-scenario tests/scenarios/sdo_smoke.yaml --junit junit.xml
```

**Python モジュール形式（常に動く）:**
```bash
python3 -m omsim.apps.scenario tests/scenarios/sdo_smoke.yaml --junit junit.xml
```

## トラブルシューティング

- **`omsim: command not found` になる場合**: コンソールスクリプト `omsim` / `omsim-scenario` は `~/.local/bin` に配置されます。
  - **原因 1**: プロビジョニング直後、PATH が `~/.local/bin` を含んでいない可能性があります。
    - 対処: `source ~/.profile` を実行するか、一度ログアウト・再ログインしてください。
  - **原因 2**: 非ログインシェル（`ssh host "コマンド"` 形式）で実行している。
    - 対処: `python3 -m omsim.apps.omsim_main` または `python3 -m omsim.apps.scenario` を使用してください。
- **`chmod +x` が効かない**: VirtualBox の共有フォルダ（vboxsf）上ではファイルモードの変更が反映されない。
  実行ビットは Windows 側のリポジトリで `git update-index --chmod=+x <file>` を実行して立てる。
- **VM を再起動すると `vcan0` が消える**: `vcan0` は永続デバイスではないため。
  `omsim-vcan.service` を `systemctl enable` していれば起動時に自動で再作成される
  （`vagrant_provision.sh` が enable まで行う）。
- **`python3 -m pytest --version` が 8.3.5 でない**: Ubuntu 20.04 には pytest 4.6.9 が同梱されており、
  PATH の解決順によってはそちらが優先されてしまうことがある。
  `python3 -m pip install --user -r requirements.txt` を実行し直し、
  `python3 -m pytest --version` で 8.3.5 になっていることを確認する。
