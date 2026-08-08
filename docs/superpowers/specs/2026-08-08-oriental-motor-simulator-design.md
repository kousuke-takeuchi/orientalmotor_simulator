# オリエンタルモーター BLVD-KRD CAN 通信シミュレータ 設計書

- 日付: 2026-08-08
- 対象リポジトリ: `C:\Users\ktake\code\keisuu\oriental_motor_simulator`
- 状態: 設計合意済み（実装計画はこの後 writing-plans で作成）

## 1. 目的

オリエンタルモーター BLVD-KRD ドライバ（BLV シリーズ R タイプ）の CANopen 通信を、実機のモーター・ドライバなしに
PC 上で再現する。CAN コマンドを送るとシミュレータ上のモーターの状態が変化し、位置・速度・トルクを読み出せる。

達成したいこと（優先順）:

1. **CAN 通信機能を完璧に網羅する。** 仕様書に書かれているドライバ挙動を、抜けなく再現する。
2. **pitakuru の oriental_motor ノードを PC 上でデバッグできるようにする。** 実機を用意せずに開発・回帰試験を回す。
3. **複数モーターを同時にシミュレーションできる。** 最低 2 台（右/左モーター）を 1 本の CAN バス上で
   独立した node_id・独立したパラメータ（それぞれの `.mxex`）・独立した状態機械として同時に動かす。
   台数は設定で増やせる。
4. 自動テスト基盤として使える（シナリオを CI で回して合否を出す）。
5. 動いている様子を Web ブラウザで見られる（MEXE02 のモニタ画面を参考にした構成）。

## 2. 対象機器と一次資料

`docs/oriental_motor/` に配置済み。仕様の正本はこれらであり、実装中の判断はここに戻って確認する。

| ファイル | 内容 | 役割 |
|---|---|---|
| `HP-5143E.pdf` (130p) | BLV series R type Driver CANopen communication profile | **通信仕様の正本。** NMT/SDO/PDO/SYNC/EMCY、Statusword ステートマシン、pv/pp/tq/hm |
| `HP-5141J.pdf` (482p) / `HP-5142E.pdf` (514p) | 取扱説明書 機能編（日/英） | **ドライバ挙動の正本。** 運転方式、入出力信号、動力遮断、アドレスコード一覧、アラーム、拡張機能 |
| `HP-5139J.pdf` (38p) / `HP-5140E.pdf` (40p) | 取扱説明書 設置・接続編（日/英） | CN4 入出力の結線、CAN 通信設定、LED 表示、アラーム一覧、タイミングチャート |
| `HM-5307J.pdf` / `HM-5308E.pdf` (28p) | モーター取扱説明書（日/英） | モーター仕様、許容荷重 |
| `BLVD-KRD_CANopen_V400.eds` | EDS (EDSVersion 4.0, FileVersion 4) | オブジェクト辞書の正本 |
| `A1806.step` / `A1861_F.step` | 3D モデル | Web 3D ビュー用（最終フェーズ） |
| `日本アクセス_右モーター.mxex` / `日本アクセス_左モーター.mxex` | MEXE02 設定ファイル | 実運用のパラメータ。CN4 の HWTO 割付変更を含む |

### 2.1 EDS から読み取った device 情報（実測）

```
VendorName=ORIENTAL MOTOR Co., Ltd.   VendorNumber=702
ProductName=BLVD-KRD                  ProductNumber=5111
BaudRate: 10/20/50/125/250/500/800/1000 kbps すべて対応
SimpleBootUpSlave=1   NrOfRXPDO=4   NrOfTXPDO=4   Granularity=4   LSS_Supported=0
```

主要オブジェクト（EDS 実測、抜粋）:

- 通信: `1000h` `1001h` `1003h`(11 sub) `1005h` `1006h` `1008h` `1009h` `100Ah` `100Ch` `100Dh`
  `1010h`(3 sub) `1011h`(3 sub) `1014h` `1016h`(2 sub) `1017h` `1018h`(3 sub) `1200h`(3 sub)
  `1400h`-`1403h` `1600h`-`1603h` `1800h`-`1803h` `1A00h`-`1A03h`
- CiA402: `603Fh` `6040h` `6041h` `605Ah`-`605Eh` `6060h`-`6062h` `6064h` `6065h` `6067h` `606Bh`-`606Fh`
  `6071h`-`6077h` `607Ah`-`607Dh` `6081h`-`6087h` `608Fh` `6091h` `6098h`-`609Ah` `60A8h` `60A9h`
  `60B8h`-`60BDh` `60D5h`-`60D8h` `60E3h` `60F2h` `60F4h` `60FDh` `60FEh` `60FFh` `6502h` `67FEh` `67FFh`
- メーカ固有: `402Ch`-`4034h`（ダイレクトデータ運転）、`403Ah` `403Ch` `403Dh` `403Eh` `403Fh`（入出力コマンド）、
  `404Bh`-`4050h`（ユーザー単位モニタ）、`4056h` `406Bh`-`407Fh` `409Bh`-`40ABh`（モニタ）、
  `40C0h`-`40D8h`（メンテナンスコマンド）、`4148h` `414Bh` `415Fh` `4160h`-`4169h` `4186h` `41A4h` `41CAh`
  `4735h` `4736h`（パラメータ）

### 2.2 EDS のバージョン差

- `docs/oriental_motor/` にあるのは **BLVD-KRD V400**（2025-11-17 作成）
- pitakuru が読み込んでいるのは `src/motors/oriental_motor/data/BLVD-KRD_CANopen_V200.eds` と
  `BLVD-KBRD_CANopen_V300.eds`

**方針: V400 を実装の基準とし、起動時に EDS を差し替えられる形にする。** V200/V300 で起動した場合、
その EDS に存在しないオブジェクトへのアクセスは仕様通り SDO abort を返す。これにより実機のファームウェア差を
シミュレータ側で吸収でき、将来 V400 機に置き換えたときの作り直しも発生しない。

### 2.3 `.mxex` の形式（実測で確定）

BOM 付きの単一行 XML。

```xml
<FileDataTree>
  <Pid>16433</Pid><Sid>0</Sid><VersionRequirement>0.0.0.0</VersionRequirement>
  <MetaDatas>
    <MetaData><Key>protocol</Key><Value>pclink2</Value></MetaData>
    <MetaData><Key>communicationdatas</Key><Value>[{"Bank":1,"Address":272,"Value":0}, ...]</Value></MetaData>
    <MetaData><Key>axisnum</Key><Value>0</Value></MetaData>
    ...
  </MetaDatas>
  <NetIds>
    <netid id="272" val="0"><att key="bank" val="1"/></netid>
    ...
  </NetIds>
</FileDataTree>
```

- 1 ファイルあたり netid 8500 件、すべて bank 1、id は 272〜18390
- **`netid == CANopen index − 0x4000`（bank 1）であることを実測で確認した。**
  EDS にパラメータとして載っている 4xxx オブジェクト 11 個すべてが mxex に存在し、値も EDS の `DefaultValue` と
  完全一致した（`4148h`=0, `414Bh`=1, `415Fh`=10000, `4160h`=1, `4163h`=30, `4169h`=18000, `4186h`=3000,
  `41A4h`=0, `41CAh`=1, `4735h`=1000, `4736h`=1000）。
  mxex に無い 61 個の 4xxx は 402Ch 系トリガ・40Cx 系コマンド・40xx 系モニタ、つまり保存対象でないものであり整合する。
- netid が 0xFFF を超える領域（4096〜18390）は RS-485 アドレスコード空間で、運転データ配列や入出力信号割付が入る。
  意味と初期値は `HP-5141J.pdf` 第7章「アドレスコード一覧」（p297-418）にある。
- **右/左 mxex の差分は 1 箇所のみ**: `netid 17152` が右=2 / 左=1。他 8499 件は完全一致。

### 2.4 被試験体（現状）

`pitakuru_ws/src/motors/oriental_motor/src/motor_control_node` は 1200 行超の Python (rospy) ノードで、
`canopen` ライブラリを使用。`canopen.Network()` + `import_from_eds` + SDO の upload/download 中心。
触っているオブジェクトは `1003h` `4032h` `409Bh` `6040h` `6041h` `6060h` `6072h` `6077h` `6083h` `6084h`
`606Ch` `60FFh`。設定は `motor_id: 1, 2` / `reduction: 100` / bitrate 500k
（`src/pitakuru/system/bin/can-start_oriental_motor.sh`、`src/pitakuru/config/motors/motors_oriental_motor.yaml`）。

**このノードは作り替える予定であるため、現状が使っている機能に実装範囲を合わせない。**
シミュレータは仕様書全体を網羅する。現行ノードとの疎通は「PC でデバッグできる」ことを最初に確認するための
マイルストーンとしてのみ使う。

## 3. 実装方針の決定事項

| 論点 | 決定 | 理由 |
|---|---|---|
| 実装言語 | **Python** | 被試験体と同じスタック。保守できる人が多い。ドライバ挙動の実装に工数を集中できる |
| CANopen スレーブ層 | **`canopen` ライブラリの `LocalNode` を使う** | SDO サーバ（expedited/segmented/block 全対応）・NMT スレーブ・Heartbeat producer・EMCY producer・EDS 読込を既に持つ。送る側と受ける側が同じライブラリなので解釈ずれが起きない |
| CAN バス | **SocketCAN の `vcan0`（python-can）** | 実機 `can0` と同じ API・同じコード。被試験体を無改造で繋げる |
| 実行環境 | **既存の Vagrant VM**（`bento/ubuntu-20.04`、`192.168.33.10`） | pitakuru の ROS1 / catkin 環境が既にある。`vcan` はカーネルローカルなので被試験体と同一インスタンスに居る必要がある |
| MEXE02 連携 | **`.mxex` ファイル読み込みのみ。MEXE02 本体との USB 通信（`pclink2`）は実装しない** | mxex が素直な XML で必要な情報が全部取れることが判明したため、実装量に対して見返りが薄い |
| モーター物理 | **運転プロファイル忠実 + 1 次遅れ追従** | 制御ロジックと通信シーケンスの検証にはこれで十分。慣性・摩擦の詳細モデルは作らない |

### 3.1 `canopen` ライブラリが提供する範囲（ソースで確認済み）

`canopen.node.local.LocalNode` は以下を持つ（作らなくてよい）:

- `SdoServer(0x600 + id, 0x580 + id, self)` — `init_upload` / `segmented_upload` / `init_download` /
  `segmented_download` / `block_upload` / `block_download` / `request_aborted` を実装。
  `SdoAbortedError` を abort コードに変換して応答し、`KeyError` は `ABORT_NOT_IN_OD` になる
- `NmtSlave(id, self)` — NMT コマンド受理と状態遷移、Heartbeat producer（`1017h` の書込みを自分で処理）
- `EmcyProducer(0x80 + id)`
- `RPDO` / `TPDO` / `PDO` オブジェクト
- `get_data` / `set_data` と `add_read_callback` / `add_write_callback`
  → 「`6040h` に書かれた」を捕まえてドライバモデルへ流す口が最初から用意されている
- `ObjectDictionary`（`import_from_eds` で実 EDS から生成）

自分で実装するもの:

- ドライバ挙動の全部（CiA402 ステートマシン、運転方式、メーカ固有 4xxx、アラーム、CN4 I/O）
- PDO の送信規則（`1800h` の transmission type / event timer / inhibit time / SYNC 起動 / 動的マッピング）
- node guarding スレーブ（`NmtSlave` は RTR 応答を持たない）
- SYNC producer / consumer（`1005h` `1006h`）
- `1010h` Store / `1011h` Restore の永続化（ファイルを擬似 EEPROM とする）
- `1003h` Pre-defined error field（11 段）

## 4. アーキテクチャ

```
[ pitakuru oriental_motor ノード (rospy + canopen) ]   ← 被試験体、無改造
[ omsim-scenario (テスト時のマスタ役) ]                 ← どちらも同じバスに乗る
                    |
                vcan0 (SocketCAN, Vagrant VM 内)
                    |
[ omsim (Python) ]
  can/       python-can socketcan bus + Notifier
  node/      canopen.LocalNode x N (node_id 1, 2 ...) + EDS(V400/V200/V300 切替)
  proto/     PDO 送信規則 / node guarding / SYNC / 1010h-1011h 永続化 / 1003h
  driver/    DriverModel x N   <-- 自作の中心。CAN を知らない
               Cia402StateMachine  (6040h/6041h, option codes)
               OperationEngine     (pv/pp/tq/hm, ダイレクトデータ, ストアード, FW-RV, I/O原点復帰)
               ProfileGenerator    (台形加減速, 起動速度, 停止方法, WRAP, 座標管理, 単位系)
               MotorPlant          (1次遅れ + 位置積分 + トルク推定)
               IoModel             (CN4 入出力割付, HWTO)
               AlarmModel          (アラーム/インフォメーション/履歴)
  params/    ParameterStore (EDS 既定値 <- mxex <- SDO の三段上書き)
  mxex/      mxex ローダ / アドレスコード表 / 差分ツール
  sim/       SimClock(1ms 固定ステップ) / Recorder(jsonl: CANフレーム+状態トレース)
  web/       FastAPI + WebSocket + 静的配信
```

### 4.1 モジュール境界（テスト容易性のため厳守する）

- **`driver/` は `can` も `canopen` も import しない。** 外向きの口は
  `read_object(index, sub)` / `write_object(index, sub, value)` / `step(dt)` / `snapshot()` の 4 つだけ。
  → CAN 抜きで pytest から直接叩ける。これが網羅テストを積み上げられる根拠。
- **`node/` は「CAN フレーム ↔ オブジェクト読み書き」の変換のみ。** ドライバ挙動を持たない。
- **`web/` と `Recorder` は `snapshot()` の購読者。** Web が居なくてもシミュレーションは完全に動く（CI ではヘッドレス）。
- **複数ノードは 1 プロセス内で動かす。** `DriverModel` はインスタンスごとに完全に独立した状態を持ち、
  クラス変数やモジュールグローバルで状態を共有しない。node_id ごとに EDS と mxex を個別に割り当てる。
  `SimClock` は 1 つで、1 ステップごとに全ノードを進める（同一バス上の時間軸を揃えるため）。
  台数は `--node` の指定数で決まり、2 台に固定しない。
- ファイルが大きくなってきたら分割する。`driver/` の 6 モジュールはそれぞれ独立して読める粒度を保つ。

### 4.2 成果物

| コマンド | 役割 |
|---|---|
| `omsim` | シミュレータ本体。`--eds` `--node <id>=<mxex>` `--web-port` `--record <path>` |
| `omsim-scenario` | YAML シナリオをマスタ役として流し、`junit.xml` と `report.html` を出す |
| `omsim-replay` | 記録した jsonl を Web 画面に再生する |
| `omsim-mxex-diff` | mxex と工場出荷値の差分表を出す（CN4 の HWTO 割付変更を検出） |

### 4.3 ディレクトリ構成

```
oriental_motor_simulator/
  pyproject.toml / requirements.txt
  docs/oriental_motor/          (既存の一次資料)
  docs/superpowers/specs/       (この設計書)
  omsim/
    can/          bus.py
    node/         local_node.py  od_bridge.py  eds.py
    proto/        pdo_rules.py  node_guarding.py  sync.py  storage.py  error_field.py
    driver/       model.py  state_machine.py  operation_engine.py  profile.py
                  motor_plant.py  io_model.py  alarm_model.py  objects.py
    params/       store.py  address_codes.yaml
    mxex/         loader.py  diff.py
    sim/          clock.py  recorder.py  manager.py
    web/          app.py  snapshot.py
    apps/         omsim.py  scenario.py  replay.py  mxex_diff.py
  tools/          extract_address_codes.py  step_to_gltf.py
  web/            Vue 3 + Vite フロントエンド
  tests/
    unit/         driver/ 各モジュールの単体テスト（網羅の主戦場）
    integration/  vcan0 越しのプロトコル結合テスト
    scenarios/    *.yaml
  scripts/        setup_vcan.sh  vagrant_provision.sh
```

## 5. 網羅スコープ（「完璧」の定義）

仕様書の 1 記述 = pytest の 1 テスト、で積み上げる。

### 5.1 通信層（HP-5143E 全章）

- NMT 全コマンド、boot-up メッセージ
- Heartbeat producer（`1017h`）/ consumer（`1016h`）
- **node guarding**（`100Ch` Guard time / `100Dh` Life time factor、RTR 応答）
- SYNC consumer / producer（`1005h` COB-ID / `1006h` Communication cycle period）
- EMCY（`1014h` COB-ID、`603Fh` エラーコード、`1001h` Error register、`1003h` エラー履歴 11 段）
- SDO: expedited / segmented / block の upload・download、全 abort コード
- RPDO x4 / TPDO x4: `1400h`-`1403h`, `1600h`-`1603h`, `1800h`-`1803h`, `1A00h`-`1A03h`。
  transmission type、inhibit time、event timer、動的マッピング
- `1010h` Store parameters / `1011h` Restore default parameters（ファイルを擬似 EEPROM に）
- `1018h` Identity object
- NMT-Start Remote Node 自動発行機能（HP-5141J p475）

### 5.2 CiA402（HP-5143E 5〜7章）

- `6040h` / `6041h` ステートマシン全遷移（Fault、Fault reaction、Quick stop、Halt、Shutdown、
  Disable operation の option code `605Ah`〜`605Eh`）
- `6060h` / `6061h` モード切替、`6502h` supported drive modes
- **pv**: `60FFh` Target velocity、`606Bh` Velocity demand、`606Ch` Velocity actual、
  `606Fh` Velocity threshold、`606Dh` Velocity window
- **pp**: `607Ah` Target position、`6081h` Profile velocity、`6082h` End velocity、
  new set-point ハンドシェイク（single set-point / set of set-points）、
  `60F2h` Positioning option code、`6067h` Position window、
  `6065h` Following error window、`60F4h` Following error actual value
- **tq**: `6071h` Target torque、`6072h` Max torque、`6087h` Torque slope、
  `6074h` Torque demand、`6077h` Torque actual value
- **hm**: `6098h` Homing method、`6099h` Homing speeds、`609Ah` Homing acceleration、
  `60E3h` Supported homing methods
- touch probe: `60B8h`〜`60BDh`、`60D5h`〜`60D8h`
- 単位系: `6091h` Gear ratio、`608Fh` Position encoder resolution、`60A8h` / `60A9h` SI unit、
  `404Bh`〜`4050h` ユーザー単位モニタ
- リミット: `607Bh` Position range limit、`607Dh` Software position limit、`607Ch` Home offset
- 加減速: `6083h` / `6084h` / `6085h` Quick stop deceleration

### 5.3 メーカ固有（HP-5141J 機能編）

- ダイレクトデータ運転（`402Ch`〜`4034h`、trigger、forwarding destination）— 第2章4節 p65
- ストアードデータ運転（運転データ表、リンク・ループ・順次/同時、`4070h`〜`4072h`）— 第2章5節 p83
- FW/RV 運転 — 第2章6節 p106
- I/O 原点復帰運転（`4160h`〜`4169h`、2 センサ / 3 センサ / 押し当て）— 第2章7節 p123
- ドライバ入力コマンド `403Eh` / `403Ah`（2nd）/ `403Ch`（自動 OFF）: START、M0〜、FWD、RVS、HOME、
  STOP、FREE、ALM-RST 等。`403Dh` NET selection data number
- `403Fh` ドライバ出力ステータス、`60FDh` Digital inputs、`60FEh` Digital outputs
- 座標管理（`40C5h` P-PRESET、`40D1h` ZSG-PRESET、`40D2h` Clear ZSG-PRESET、`41CAh` WRAP）— 第1章2節 p31
- 停止動作（即停止・減速停止・`4735h` カスタム停止レート・`4736h` カスタム停止時間、
  `4186h` アラーム発生時の停止タイムアウト）— 第1章3節 p34
- トルク制限（`4032h`、`415Fh` JOG/HOME トルク制限値）— 第1章4節 p39
- ATL 機能（`414Bh`）— 第1章5節 p40
- ドライバ状態とモーター励磁 — 第1章6節 p42
- モニタ類: `406Bh` トルク、`406Ch` 負荷率、`406Dh` 積算負荷、`4073h` 位置偏差、`4075h` 速度偏差、
  `4078h` 過負荷率、`407Ah` / `407Fh` トリップメータ、`407Bh` 現在情報、`407Ch` ドライバ温度、
  `407Dh` モーター温度、`407Eh` オドメータ、`409Bh` 主電源電流、`409Ch`〜`409Fh` 電力/電力量、
  `40A1h` 総通電時間、`40A2h` 起動回数、`40A3h` インバータ電圧、`40A4h` 主電源電圧、
  `40A9h` 連続通電時間、`40AAh` / `40ABh` RS-485 バイトカウンタ、`4056h` 現在の通信異常
- メンテナンスコマンド: `40C0h` アラームリセット、`40C2h` アラーム履歴クリア、`40C6h` Configuration、
  `40CDh` ラッチ情報クリア、`40CEh` シーケンス履歴クリア、`40D0h` ETO クリア、`40D3h` 情報クリア、
  `40D6h`〜`40D8h` 各種クリア
- パラメータ: `4148h` 絶対座標未設定時の絶対位置決め許可、`41A4h` モーター回転方向、その他
- 拡張機能（第9章 p451）: ゲインチューニング、振動抑制、仮想入力、ユーザー出力、データ転送、積算負荷、
  負荷状態モニタ、検出速度モニタ、ラッチ機能、**ドライバシミュレーションモード（p470）**、ドライバの LED

### 5.4 CN4 入出力と動力遮断（HP-5141J 第3章 p141・第4章 p201、HP-5139J 6-4）

- 入力信号・出力信号の全種類と割付、汎用信号、タイミングチャート（第3章 p198）
- **HWTO（動力遮断機能）の状態遷移と関連出力（EDM 等）** — BLVD-KRD は第4章 p201-212
- ここが mxex 連携の主目的（CN4 の HWTO ピン役割が既定値から変更されている）

### 5.5 アラーム（HP-5141J 第8章 p419）

- アラーム全コード（発生条件・停止方法・解除方法・履歴）— p420
- インフォメーション全コード — p438
- **シミュレータ側から意図的に発生させられるようにする**（異常系テストのため）。
  Web の注入ボタンとシナリオの `inject_alarm` ステップの両方から。

### 5.6 モーター物理モデル

- 1ms 固定ステップ
- 指令速度への 1 次遅れ追従（時定数はパラメータ）、位置は積分
- トルクは推定値（加速トルク + 一定負荷トルク）
- 減速比（pitakuru は `reduction: 100`）と単位系変換（`6091h` / `608Fh` / `60A8h` / `60A9h`）を通す

## 6. MEXE02 連携

- `omsim/mxex/loader.py`: `.mxex` → `{(bank, netid): value}` →
  `netid < 0x1000` は `netid + 0x4000` で CANopen オブジェクトへ、それ以外はアドレスコード表経由で内部パラメータへ
- `tools/extract_address_codes.py`: `HP-5141J.pdf` p297-418 から
  `netid → (名称, 初期値, 単位, 範囲, 反映タイミング)` の YAML を生成。
  生成物 `omsim/params/address_codes.yaml` をリポジトリにコミットし、再生成可能にする
- `omsim-mxex-diff`: mxex と工場出荷値の差分表を出す。CN4 の HWTO 割付変更がここに出る。
  右/左 mxex の唯一の差分 `netid 17152`（右=2 / 左=1）の正体もここで確定する
- パラメータの優先順位: **EDS 既定値 ← mxex ← 起動後の SDO 書込み**（後勝ち）
- 起動時の指定: `omsim --eds BLVD-KRD_CANopen_V400.eds --node 1=右モーター.mxex --node 2=左モーター.mxex`

## 7. Web 画面

FastAPI + WebSocket。フロントエンドは Vue 3 + Vite（pitakuru と同じスタック）。
VM の `192.168.33.10:8080` を Windows のブラウザから見る。MEXE02 のモニタ構成に寄せて 5 ペイン。

1. **ステータスモニタ** — ノードごとに NMT 状態、`6041h` Statusword のビット別ランプ、`6061h` 現在モード、
   指令/現在の位置・速度・トルク、負荷率、電圧、温度
2. **波形モニタ** — 位置・速度・トルクの時系列。トリガ条件と時間軸ズーム
3. **I/O モニタ** — CN4 入力/出力の各信号ランプ、割付名（mxex 由来）、HWTO 状態
4. **アラームモニタ** — 現在のアラーム/インフォメーション、履歴 10 件、**手動注入ボタン**
5. **CAN フレームログ** — candump 相当 + CANopen デコード表示
   （`SDO wr 6040h:00 = 000Fh`、`TPDO1 -> 6041h=0237h, 6064h=12345` の形）。フィルタと停止/再開

`omsim-replay` で jsonl を再生すると同じ画面が CI の失敗解析に使える。
3D ビュー（STEP → glTF 変換して three.js）は最終フェーズ。

## 8. テスト戦略

| 層 | 手段 | 内容 |
|---|---|---|
| ユニット | pytest | `driver/` を CAN 抜きで直接叩く。仕様書 1 記述 = 1 テスト。**網羅の主戦場** |
| プロトコル結合 | pytest + `vcan0` | `omsim` を起動し `canopen` マスタ役から SDO/PDO/NMT を投げて応答を検証 |
| シナリオ | `omsim-scenario` | YAML でシーケンスと期待値を書き、`junit.xml` + `report.html` を出す |

`omsim-scenario` は P0 で最小版（`nmt` / `sdo_write` / `sdo_read` / `expect` / `wait` / `pdo_send` の 6 ステップと
`junit.xml` 出力）を作り、以降のフェーズで機能を追加するごとにシナリオを足していく。
`report.html` と CI 統合は P7。

シナリオ YAML の形式:

- トップレベル: `name`（必須）、`nodes`（使用する node_id、既定は全ノード）、`steps`（必須）
- ステップ種別: `nmt`（`start` / `stop` / `pre-operational` / `reset` / `reset-comm`）、
  `sdo_write: {node, index, sub, value}`、`sdo_read: {node, index, sub}`、
  `expect: {node, index, sub, value, mask, tolerance, timeout}`、`wait: {seconds}`、
  `pdo_send: {node, pdo, data}`、`inject_alarm: {node, code}`、`set_input: {node, signal, state}`
- `node` を省略した場合は `nodes` の全ノードに適用する（2 台同時テストを書きやすくするため）

```yaml
name: pv モードで目標速度に到達する
steps:
  - nmt: start
  - sdo_write: {index: 0x6060, value: 3}      # pv
  - sdo_write: {index: 0x6040, value: 0x000F} # Operation enabled
  - expect: {index: 0x6041, mask: 0x006F, value: 0x0027, timeout: 1.0}
  - sdo_write: {index: 0x60FF, value: 1000}
  - expect: {index: 0x606C, value: 1000, tolerance: 10, timeout: 3.0}
```

### 8.1 複数ノードのテスト要件

以下は独立したテスト項目として必ず持つ。1 台では通るが 2 台で壊れる類のバグを捕まえるため。

- 2 台に別々の目標速度を与え、互いに干渉しないこと（`606Ch` がそれぞれ独立に追従する）
- 一方だけを Fault 状態にしても他方が運転を継続すること
- 一方だけに HWTO を入れても他方が影響を受けないこと
- 右/左で異なる mxex を割り当てたとき、パラメータが混ざらないこと
  （右/左の唯一の差分 `netid 17152` が正しく別値で保持される）
- 2 台の TPDO が同一バス上で衝突せず、COB-ID が node_id ごとに正しくずれていること
- SDO を 2 台に並行に投げても取り違えないこと
- 一方の NMT リセットが他方の状態を壊さないこと

### 8.2 最重要マイルストーン

pitakuru の `motor_control_node` を Vagrant VM で無改造起動し、`vcan0` 越しに omsim 2 ノード
（`motor_id` 1, 2）と繋いで、**モーターが無くても回転指令が通り速度が返ることを確認する**。
この時点で「PC でデバッグできる」が成立する。

## 9. エラー処理

- 未定義オブジェクトへのアクセス → 仕様通り SDO abort（`0x06020000` 等）
- 範囲外値の書込み → `0x06090030`
- 読み取り専用への書込み → `0x06010002`
- **シミュレータ自身の内部不整合は即座に落とす。** テスト基盤なので、黙って続行して嘘の合格を出すのが最悪。
- 仕様が読み取れない箇所は `NotImplementedError` を投げ、シナリオ側で「未実装に触れた」として検出できるようにする。
  未実装オブジェクトの一覧をコマンドで出せるようにし、網羅の進捗を可視化する。

## 10. 実行環境

- Vagrant VM: `bento/ubuntu-20.04`、`192.168.33.10`、8GB / 4 CPU
  （`pitakuru_ws/src/Vagrantfile`。synced_folder は `pitakuru_ws/src` → `/home/vagrant/KEISUU/develop/src`）
- `vcan0` セットアップ: `sudo modprobe vcan` → `sudo ip link add dev vcan0 type vcan` →
  `sudo ip link set up vcan0`。systemd unit で永続化する
- WSL2 も代替として成立する（カーネル `6.18.33.2-microsoft-standard-WSL2` は `CONFIG_CAN=m` /
  `CONFIG_CAN_VCAN=m` で `vcan.ko` を同梱していることを確認済み）。ただし ROS1 環境が既にある Vagrant VM を第一選択とする。

## 11. フェーズ計画

| Phase | 内容 |
|---|---|
| P0 | リポジトリ骨格、Vagrant への配置、`vcan0` セットアップ、EDS 読込、`LocalNode` 複数台、SDO 疎通、pytest 骨格、CAN フレームログ、`omsim-scenario` 最小版 |
| **P1** | **CiA402 ステートマシン + pv + アラーム基礎 + 単位系。pitakuru ノードとの疎通達成（8.2 のマイルストーン）。この時点で 2 ノード同時動作を成立させる** |
| P2 | Web 可視化 第1弾（ステータス / 波形 / CAN ログ） |
| P3 | PDO 完全対応（4+4、動的マッピング、transmission type、event timer、inhibit）、SYNC、Heartbeat、node guarding、EMCY、`1003h` |
| P4 | pp / hm / tq、停止動作、option code 群、touch probe、リミット |
| P5 | メーカ固有運転（ダイレクトデータ / ストアード / FW-RV / I/O 原点復帰）、CN4 I/O + HWTO、mxex ローダ + アドレスコード表抽出 + diff ツール |
| P6 | モニタ・メンテナンスコマンド全部、`1010h` / `1011h` 永続化、拡張機能、アラーム全コード、I/O モニタとアラームモニタ画面 |
| P7 | シナリオランナー本格版（`report.html` / `junit.xml`）、CI、3D ビュー、replay |

## 12. 既知のリスク

- **VM は Ubuntu 20.04 = Python 3.8。** `canopen` / `python-can` / `FastAPI` のバージョンを 3.8 対応に固定する
  必要がある（requirements で pin）。`canopen` の最新版が 3.8 を切っている場合は対応する最終版を使う
- `oriental_motor_simulator` は pitakuru の synced_folder 外にあるので Vagrantfile に `synced_folder` を 1 行足す。
  過去に共有フォルダが自動マウントされず手動 `vboxsf` マウントが必要だった事例があるため、セットアップ手順に含める
- `vcan0` 作成には `sudo` が必要。VM のプロビジョニングに入れて systemd で永続化する
- **Python 3.8 + 1ms ステップの負荷は測定して判断する。** 厳しければステップを 2〜5ms に落とす、
  またはホットパスだけ Cython 化する。言語の全面変更は不要
- アドレスコード表の PDF 抽出は表構造が崩れる可能性がある。抽出結果は EDS の `DefaultValue` と
  突き合わせて検証し（4xxx の 11 件で照合できる）、崩れた箇所は手で補正して YAML に固定する
