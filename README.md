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

## 3D モニタ

`--web-port` を付けて起動すると、Web の「3D モニタ」ペインに node ごとのモーターが並び、
実位置（`6064h`）に合わせて軸が回ります。ドラッグで回転、ホイールでズーム。
動力遮断中（HWTO）はモーターが赤くなります。

形状は **`docs/oriental_motor/*.step` の本物**をメッシュ化したものです
（`scripts/step_to_mesh.py` で生成し、`omsim/web/static/models/*.stl` に置いています）。
STEP では housing と軸が 1 つのソリッドで軸だけを回せないため、出力軸の軸線
（原点まわり・Z 軸。半径 47mm の円筒面から実測）の延長上に回転指標を置き、
それが `6064h` に合わせて回ります。

メッシュの再生成（gmsh は変換のときだけ必要で、実行時の依存ではありません）:

```bash
pip3 install --user gmsh
python3 scripts/step_to_mesh.py docs/oriental_motor/A1861_F.step     omsim/web/static/models/A1861_F.stl --size 8
```

外形寸法だけを見たいときは `python3 scripts/step_bbox.py docs/oriental_motor/A1806.step`。

Three.js は `omsim/web/static/vendor/` に同梱しています（オフライン前提のため CDN を使わない）。
版とライセンスは `omsim/web/static/vendor/README.md` を参照してください。

## HWTO（動力遮断機能）と CN4 の配線

安全リレーが HWTO 入力をどう駆動するかを切り替えて、標準の 2 重系配線でも、実機の
片系配線でもシミュレートできます。

```bash
python3 -m omsim.apps.omsim_main --node 1 --node 2 --wiring pitakuru --web-port 8080
```

| プリセット | HWTO1（CN4 11/12） | HWTO2（CN4 26/27） | 用途 |
|---|---|---|---|
| `standard`（既定） | 安全リレー | 安全リレー | 仕様どおりの 2 重系 |
| `pitakuru` | 安全リレー | ジャンパ短絡（常時 ON） | 実機（図面 08015VA-24M-AA-00）の片系配線 |
| `none` | ジャンパ短絡 | ジャンパ短絡 | 動力遮断機能を使わない配線 |

各チャンネルのソースは `relay` / `jumper` / `open` から個別にも選べます（Web のパネル、
または `POST /api/wiring`）。安全リレーの入切は Web のボタン、`POST /api/wiring`、
シナリオの `relay:` ステップで行えます。

```yaml
  - relay: off      # omsim 側 --web-port、シナリオ側 --web-url が必要
```

挙動（HP-5141J 4 章 実測）:

- HWTO1 OFF = インバータ上アーム遮断、HWTO2 OFF = 下アーム遮断。**どちらか一方でも
  OFF ならトルクは出せず、無励磁になってフリーランで止まり、電磁ブレーキが保持されます。**
- **両方 OFF** で「動力遮断+ETO 状態」。入力を戻しただけでは復帰せず、`40D0h`（Clear ETO）
  で解除します。
- `60FDh` bit3 が「どちらかの HWTO 入力が active」を表します。
- 1ms 以下のオフショットパルスでは動作しません。
- アラーム: `FF53h`（HWTO 入力回路異常）/ `FF68h`（HWTO 入力検出）。どちらも MEXE02 の
  パラメータ次第で、実機の設定（`docs/oriental_motor/address-codes.md` 参照）は
  **両方とも無効**のため片系配線でもアラームは出ません。

**既知の制限**: 動力遮断後の減速はフリーランの慣性を模擬せず即座に 0 になります
（電磁ブレーキが保持される前提。ブレーキ無しモーターの惰走は未対応）。

## 運転モード (P4)

`6060h` で切り替え、`6061h` に反映されます。サポートするモードは次のとおりです。

| 値 | モード | 主なオブジェクト |
|---|---|---|
| 1 | pp (Profile Position) | `607Ah` 目標位置 / `6081h` プロファイル速度 / `6083h`・`6084h` 加減速 |
| 3 | pv (Profile Velocity) | `60FFh` 目標速度 |
| 4 | tq (Profile Torque) | `6071h` 目標トルク / `6087h` トルク傾き / `6072h` 最大トルク |
| 6 | hm (Homing) | `6098h` 方式 / `6099h` 速度 / `609Ah` 加速度 / `607Ch` 原点オフセット |

**Statusword の bit12 / 13 / 15 はモードで意味が変わります**（pv: Speed is 0 / pp: Set point
acknowledge・Following error / hm: Homing attained・Homing error / 共通: bit15 Torque limit）。
Web のステータスモニタも `6061h` を見て名前を切り替えます。

### pp の使い方

`607Ah` に目標位置を書き、Controlword の bit4（New set point）を 0→1 にすると動き出します。
bit5=1 で運転中の即時差し替え、bit6=1 で相対位置決め、bit8=1 で `605Dh` に従った減速停止。

### hm の使い方

サポートする方式は **17 / 18**（リミットセンサ）、**24 / 28**（HOME センサ）、
**35 / 37**（現在位置を原点。既定は 37）。index pulse (ZSG-N) を使う 1 / 2 / 8 / 12 と
メーカ固有の −1 は未実装で、書き込むと SDO abort になります。
センサ入力は `DriverModel.set_limit_inputs(fw_ls=..., rv_ls=..., home=...)` で与えます
（CN4 の実配線は P5）。

### 停止動作の option code

`605Ah`（quick stop、既定 2）/ `605Bh` / `605Ch` / `605Dh`（0 は仕様上予約なので abort）/
`605Eh`。`605Ah` は実際に効きます（`2` は `6085h` のランプ、`1` は通常減速、`0`/`−1` は即時、
`5`/`6` は quick-stop-active に留まる）。`−3`/`−2` は 4735h/4736h の単位が未確認のため abort します。
`605Bh`/`605Ch`/`605Eh` は値の保持のみで、理由は `--list-stubs` に出ます。

### リミットと touch probe

- `607Dh` ソフトウェアリミットは**原点復帰完了後にだけ**有効（`Min ≥ Max` や両方 0 は無効）。
  `607Ch` 原点オフセットを引いた値と比較します。
- リミットセンサに当たると `Statusword` bit11（Internal limit active）が立ち、
  その方向だけ止まります（反対方向へは動けます）。`60FDh` の bit0/1/2 で状態を読めます。
- touch probe は `60B8h`（機能）/`60B9h`（状態）/`60BAh`-`60BDh`（ラッチ値）/
  `60D5h`-`60D8h`（カウンタ）。トリガは `DriverModel.trigger_touch_probe(probe, edge)` で与えます。
  ZSG-N をトリガ源にする設定は未実装のため abort します。

## メーカ固有運転 / リモート I/O / mxex (P5)

### ダイレクトデータ運転

CiA402 の運転モードとは独立した、オリエンタルモーター固有の運転系統です。
`402Dh` に運転方式、`402Eh`/`402Fh`/`4030h`/`4031h` にデータを書き、`4033h`
（反映トリガ）を書いた瞬間に運転が始まります。

- `4033h` は **上位 16bit = ライフタイム / 下位 16bit = 反映トリガ**。
  どちらかが範囲外なら**上位下位とも反映しません**（仕様どおり）。
- 反映トリガ `1`（`2`/`3` も同じ）で通常起動。**同じ値を書いても起動しません**。
- トリガ自動クリア（既定有効）で下位 16bit は 0 に戻ります。
- 運転データは**トリガを書いた時点の値が使われます**（以後の書き換えは次のトリガまで効かない）。
- 対応する運転方式: `0` 減速停止 / `1` 絶対位置決め / `2` 相対位置決め（指令位置基準）/
  `3` 相対位置決め（検出位置基準）/ `16` 連続運転（速度制御）/ `32` 即停止。
  それ以外（WRAP 系・押し当て系・連続運転（位置制御）・モーション拡張モード）は
  一覧にはありますが未実装で、書き込むと SDO abort になります。
- 単位指定起動（反映トリガ 4-19）と個別項目トリガ（負値）も未実装で abort します。

例: `tests/scenarios/direct_data_demo.yaml`

### リモート I/O

`60FEh:01` と `403Eh` は同じレジスタで、bit16-31 が R-IN0..15
（S-ON / PLOOP-MODE / TRQ-LMT / CLR / QSTOP / STOP / FREE / ALM-RST / D-SEL0..7）。
`403Fh` と `60FDh` の bit16-31 が R-OUT0..15
（SON-MON / PLOOP-MON / TRQ-LMTD / RDY-DD-OPE / ABSPEN / STOP_R / FREE_R / ALM-A /
SYS-BSY / IN-POS / RDY-HOME-OPE / RDY-FWRV-OPE / RDY-SD-OPE / MOVE / VA / TLC）。

現在効くのは FREE（励磁 OFF）、STOP（減速停止）、QSTOP（クイックストップ）と、
出力側の SON-MON / ALM-A / MOVE / VA / TLC / TRQ-LMTD です。
機能割付の変更（DIN/DOUT/R-I/O 機能選択）は未実装で、既定割付のみを扱います。

### mxex の適用と比較

```bash
# 起動時に各ノードへ適用する (適用件数・未知・拒否を必ず表示)
python3 -m omsim.apps.omsim_main --node 1=右モーター.mxex --node 2=左モーター.mxex

# 2 つの mxex を netid 単位で比較する
python3 -m omsim.apps.omsim_main --mxex-diff 右モーター.mxex 左モーター.mxex
```

netid と CANopen index の対応は `CANopen index = 0x4000 + netid`（bank 1）。
`docs/oriental_motor/address-codes.md` に、アドレスコード表からの裏取りと
実機 mxex の実測値を記録しています。

## アラーム / 永続化 / モニタ (P6)

### アラームコード

メーカ固有アラームの EMCY コードは **`0xFF00 | アラームコード`**、error register は `81h`
（HP-5143E 4.5 実測）。通信系だけ CiA301 標準コード（`8110h`/`8120h`/`8130h`/`8140h`/`8210h`、
error register `11h`）です。全 36 コードの表は `omsim/driver/alarm_codes.py` にあり、
ALM-RST で解除できるか、無励磁が即時か減速後かも持っています。

```python
model.inject_alarm(0x30)   # EMCY と error register は表から決まる
```

### パラメータの保存 / 既定値復帰

- `1010h:01` に `"save"`（`65766173h`）で全パラメータ保存、`:02` で通信パラメータのみ
- `1011h:01` に `"load"`（`64616F6Ch`）で既定値へ復帰、`:02` で通信パラメータのみ
- 署名が違えば SDO abort `08000020h`
- 保存先はプロセス内（実機の不揮発メモリ相当）。既定値の正は「生まれたての DriverModel」

### モニタとメンテナンスコマンド

ユーザー単位モニタ（`404Bh`-`4050h`）、速度偏差（`4075h`）、トルク・負荷率・過負荷率
（`406Bh`/`406Ch`/`4078h`）、稼働時間（`40A1h`/`40A9h`）、走行距離（`407Eh`/`407Fh`/`407Ah`）。
メンテナンスコマンドは `40C2h`（アラーム履歴クリア）、`40C5h`（P-PRESET）、
`40D7h`/`40D8h`（トリップメータクリア）。

**電圧・温度・電力量（`407Ch`/`407Dh`/`40A3h`/`40A4h`/`409Ch`）は物理モデルが無く、
読み出せますが常に 0 を返すだけです**（`--list-stubs` に理由が出ます）。

Web には**アラームモニタ**（現在アラームと `1003h` 履歴をコード名つきで表示）と
**I/O モニタ**（R-IN / R-OUT を既定機能名でランプ表示）があります。

## シナリオのレポートと再生 (P7)

### report.html

```bash
python3 -m omsim.apps.scenario tests/scenarios/two_nodes_pv.yaml     --junit junit.xml --report report.html --record-path rec.jsonl
```

各ステップの PASS/FAIL・所要時間・実測値を 1 枚の HTML にまとめます。外部を一切
参照しないのでオフラインでも CI の成果物としても開けます。`--record-path` に
`omsim --record` が書いた jsonl を渡すと CAN ログの末尾を添えます
（渡さなければ「記録はありません」と明記します）。

### 再生 (replay)

```bash
# 記録する
python3 -m omsim.apps.omsim_main --node 1 --node 2 --record rec.jsonl

# 記録を再生する (シミュレーションも CAN も動かさない)
python3 -m omsim.apps.omsim_main --replay rec.jsonl --web-port 8080 --web-host 0.0.0.0
```

再生ペインのスライダで任意の時刻へ移動できます。**再生は読み取り専用**で、
配線・安全リレーの操作はできません（HWTO パネルは自動的に隠れます）。

### CI

`.github/workflows/ci.yml` が Ubuntu ランナーで `vcan0` を作り、Python 3.8 で
全テストを回します。**skip が出たら失敗させる**ので、vcan が使えないまま
「全部通った」ように見えることはありません。シナリオの `report.html` /
`junit.xml` / `rec.jsonl` は成果物として残ります。

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
