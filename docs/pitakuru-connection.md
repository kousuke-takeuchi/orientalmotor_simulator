# pitakuru `oriental_motor` ノードとの疎通確認（P1 マイルストーン）

実施日: 2026-08-08。実施環境: Vagrant VM (Ubuntu 20.04 / Python 3.8.10 / ROS1 Noetic)。
pitakuru は `/home/vagrant/KEISUU/develop`（branch `feature/p0-p1`、無改造）、
omsim は `/home/vagrant/KEISUU/omsim`（branch `feature/p0-p1`）。

**結論: pitakuru の `oriental_motor/motor_control_node` を無改造で起動し、
omsim（実機なし）に対して ROS トピック経由で回転指令を送り、`606Ch`
（Velocity actual value）に指令通りの速度が返ることを確認した。**
ただし、そのままでは起動できず、下記の 2 つの対処が必要だった。

## 1. can0（vcan）作成

```bash
sudo modprobe vcan
sudo ip link add dev can0 type vcan
sudo ip link set up can0
ip -o link show can0
```

実測出力:

```
7: can0: <NOARP,UP,LOWER_UP> mtu 72 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000\    link/can
```

この VM に実機 CAN は無く、事前に `can0` は存在しなかったため衝突なし。

## 2. omsim の起動（V200 EDS）

EDS を pitakuru と同じものにするため `docs/oriental_motor/` へコピー:

```bash
cp /home/vagrant/KEISUU/develop/src/motors/oriental_motor/data/BLVD-KRD_CANopen_V200.eds \
   /home/vagrant/KEISUU/omsim/docs/oriental_motor/
cp /home/vagrant/KEISUU/develop/src/motors/oriental_motor/data/BLVD-KBRD_CANopen_V300.eds \
   /home/vagrant/KEISUU/omsim/docs/oriental_motor/
```

`scripts/run_with_pitakuru.sh`（本タスクで新規作成）:

```bash
python3 -m omsim.apps.omsim_main \
    --channel can0 \
    --eds BLVD-KRD_CANopen_V200.eds \
    --node 1 \
    --node 2 \
    --record /tmp/omsim-pitakuru.jsonl
```

起動確認（`/tmp/omsim-pitakuru.jsonl` 先頭の state レコード、boot 直後）:

```json
{"state": "switch-on-disabled", "statusword": 4688, "mode": 3,
 "actual_velocity_rpm": 0.0, "actual_position": 0}
```

**使用 EDS: `BLVD-KRD_CANopen_V200.eds`**（pitakuru が実際に読んでいるもの。V400 ではない）。

## 3. pitakuru ノード起動 — 1 回目は失敗（vcan の state 判定）

```bash
cd /home/vagrant/KEISUU/develop && source devel/setup.bash
roscore &
cd /home/vagrant/KEISUU/develop && roslaunch oriental_motor test.launch
```

**無改造の状態では起動に失敗した。** 実測ログ:

```
[INFO] [...]: can up
[INFO] [...]: Fail setup can
Traceback (most recent call last):
  ...
  File ".../motor_control_node", line 605, in start_canopen
    self.alert_pub.publish(diagnostic_msg)
AttributeError: 'OrientalMotorNode' object has no attribute 'alert_pub'
```

**原因（実測で特定）:**

- `motor_control_node` の `is_can_interface_up()` は `ip link show can0` の
  出力に文字列 `'state UP'` が含まれるかどうかで CAN インターフェースの
  UP/DOWN を判定している。
- しかし vcan ドライバ（`vcan.c`）はキャリア制御を実装しないため、
  `ip link set can0 up` を実行しても `state` は常に `UNKNOWN` のままになる
  （実測: `ip -d link show can0` → `state UNKNOWN`, `/sys/class/net/can0/operstate` → `unknown`）。
  実 CAN アダプタ（socketcan 経由の物理デバイス）ならこの判定は機能するが、
  vcan では原理的に成立しない。
- その結果 `can_up()` が `False` を返し `start_canopen()` が
  「USB disconnected」扱いで異常終了しようとするが、その異常系パス自体に
  pitakuru 側のバグがあり（`alert_pub` が生成される前に使われる）
  `AttributeError` で落ちる。これは pitakuru 側の既存バグであり、
  `pitakuru_ws` は無改造の方針のため修正していない。

**この確認のためだけの回避策（pitakuru_ws は一切変更していない）:**
`ip link show` の出力の `state UNKNOWN` を `state UP` に書き換えるだけの
シェルスクリプトを VM の `/tmp/ip-shim/ip` に作り、`roslaunch` 実行時だけ
`PATH=/tmp/ip-shim:$PATH` を前置してこのシムを優先させた。
本物の `ip` コマンドへの委譲であり、`link show` 以外は素通し。
ファイルは VM のローカル `/tmp` にのみ置いており、`pitakuru_ws` /
`oriental_motor_simulator` のどちらのリポジトリにもコミットしていない
一時的な検証専用の回避策。

再実行コマンド:

```bash
PATH=/tmp/ip-shim:$PATH roslaunch oriental_motor test.launch
```

## 4. abort されたオブジェクト一覧と omsim への追加実装

シムを入れて `can_up()` を通した後、SDO 通信自体は成立したが、
omsim が未実装のオブジェクトへの書き込みで順に abort → ノードが例外で
落ちることを繰り返した。**abort コード `0x06010002`
（Attempt to write a read only object）は omsim の `ObjectRouter.write()` が
未登録オブジェクトに対して返すデフォルトの abort であり、
「V200 の EDS には存在するが omsim に書き込みハンドラが無い」ことを示す。**

| 順序 | index:sub | 名称（EDS） | 検出方法 | 対処 |
|---|---|---|---|---|
| 1 | `60FEh:01` | Digital outputs (Physical outputs) | candump フレーム解析（下記） | omsim にハンドラ追加 |
| 2 | `6072h:00` | Max torque | candump フレーム解析（下記） | omsim にハンドラ追加 |
| 3 | `4032h:00` | Direct data operation torque limiting value | Python 側 `SdoAbortedError` の traceback（candump は次の再起動で上書きされ生データは残っていない） | omsim にハンドラ追加 |
| 4 | `6081h:00` | Profile velocity | 同上（traceback のみ、生フレーム未保存） | omsim にハンドラ追加 |
| 5 | `1016h:01` | Consumer heartbeat time | ソース静的解析（`ctrl.motor_node.sdo.download(0x1016, 0x01, ...)`、`start_heartbeat()` 内）。実際に abort されるのを待たず、6081 修正時に事前実装した | omsim にハンドラ追加（予防的） |

`60FEh:01` と `6072h:00` の abort は candump の生フレームで確認できた
（`candump -tz can0` 抜粋、`80` で始まる応答が abort）:

```
 (000.304418)  can0  601   [8]  23 FE 60 01 00 00 80 01
 (000.304952)  can0  581   [8]  80 FE 60 01 02 00 01 06
 (000.306953)  can0  601   [8]  2B 72 60 00 10 27 00 00
 (000.307376)  can0  581   [8]  80 72 60 00 02 00 01 06
```

デコード: `581` フレームの先頭バイト `80` = abort。`80 FE 60 01` →
index=0x60FE, sub=0x01。データ部 `02 00 01 06` をリトルエンディアンで読むと
abort code = `0x06010002`（Attempt to write a read-only object）。
`80 72 60 00` → index=0x6072, sub=0x00、同じ abort code。

`4032h` / `6081h` は同様のパターンで発生していたことを Python 側の
`canopen.sdo.exceptions.SdoAbortedError: Code 0x06010002` の traceback で
確認したが、この 2 件については candump の生フレームは次の再起動で
上書きしてしまい保存できていない（**推測ではなく「保存できなかった」
という事実として記録する**）。

いずれも V200 の EDS には `AccessType=rww`（4032 は明記なし・EDS上は
rww 相当）または `rww`/`ro` で存在しており、omsim 側が単に未実装
だっただけだった。5 件とも `omsim/driver/model.py` の `DriverModel` に
最小限のリーダ/ライタを追加して解消した:

- `6072h`（Max torque、千分率 0-10000）: 保持のみ、実トルク制限のモデルへの反映は無し
- `60FEh:01`（Digital outputs）: 保持のみ
- `1003h`（Pre-defined error field）: sub0 読み取り = 履歴件数、sub0 に 0 書き込みで履歴クリア、sub1-10 読み取り = `AlarmModel.history`
- `4032h`（Direct torque limit）: `6072h` と同じ値を共有
- `409Bh`（Main power supply current）: 固定で 0 を返す最小実装
- `6081h`（Profile velocity）: 保持のみ、`TrapezoidProfile` への反映は無し
- `1016h:01`（Consumer heartbeat time）: 保持のみ、Heartbeat consumer 自体は未実装のまま

**5 件追加後も `python3 -m pytest -v` は 165 件全て passed（SKIP 0 件）。**

## 5. 回転指令が通り速度が返ることの確認

`enable_all` → 5 秒以内に速度指令が来ないと安全のため自動で
quick stop する挙動を確認したため、`enable_all` 発行直後から速度指令の
継続送信（`rostopic pub -r 20`）を開始した。

使用したトピック・型・値:

```bash
rostopic pub -1 /motor_control_node/command/enable_all std_msgs/Bool 'data: true'

rostopic pub -r 20 /motor_control_node/control/velocity motor_msgs/ControlVelocity \
  '{header: auto, motor_id: 1, speed: 3.0}'    # motor_id=1, +3.0 rad/s

rostopic pub -r 20 /motor_control_node/control/velocity motor_msgs/ControlVelocity \
  '{header: auto, motor_id: 2, speed: -2.0}'   # motor_id=2, -2.0 rad/s
```

`ControlVelocity.msg`: `Header header / uint32 motor_id / float32 speed [rad/s]`。

pitakuru 内部ログ（`/home/vagrant/.ros/log/.../motor_control_node-1.log`、
rospy 内部ログのため出力バッファに滞留せずタイムスタンプ付きで記録される。
nohup のリダイレクト先 `/tmp/motor_node.log` は Python 側の stdout
ブロックバッファリングにより更新が遅延したため、この内部ログを一次情報とした）:

```
[rosout][INFO] 2026-08-08 17:16:42,125: start free_off
[rosout][INFO] 2026-08-08 17:16:42,128: start switch_on
[rosout][INFO] 2026-08-08 17:16:42,130: start disable_op
[rosout][INFO] 2026-08-08 17:16:42,132: start enable_op
[rosout][INFO] 2026-08-08 17:16:42,134: start check_motor_not_ready
[rosout][INFO] 2026-08-08 17:16:42,136: Motor ID 1 : Enabled
[rosout][INFO] 2026-08-08 17:16:42,147: Motor ID 2 : Enabled
...(約 3 分間、速度指令を送り続けている間は "Not ready" も quick_stop も出ない)...
[rosout][ERROR] 2026-08-08 17:19:51,115: motor cmd vel time out last time1786209588.8735502: motor1
```

`speed 指令を止めてから 3 分後にタイムアウトで自動 quick stop` している
ことから、`timeout: 3.0` [s] のパラメータ通りに安全機構が動作している
ことも合わせて確認できた。

`candump -tz can0` 抜粋（速度指令が流れている間、node1/node2 それぞれの
statusword 読み取りと `60FF`（Target velocity）の書き込みが独立に流れている）:

```
 (543.665902)  can0  601   [8]  40 41 60 00 00 00 00 00
 (543.666120)  can0  581   [8]  4B 41 60 00 37 06 00 00
 (543.666460)  can0  601   [8]  40 6C 60 00 00 00 00 00
 (543.666695)  can0  581   [8]  43 6C 60 00 68 FA FF FF
 (543.667041)  can0  601   [8]  40 9B 40 00 00 00 00 00
 (543.667201)  can0  581   [8]  43 9B 40 00 00 00 00 00
 (543.667610)  can0  602   [8]  40 41 60 00 00 00 00 00
 (543.667808)  can0  582   [8]  4B 41 60 00 37 06 00 00
 (543.669670)  can0  602   [8]  40 6C 60 00 00 00 00 00
 (543.669931)  can0  582   [8]  43 6C 60 00 BA 03 00 00
 (543.670140)  can0  602   [8]  40 9B 40 00 00 00 00 00
 (543.670409)  can0  582   [8]  43 9B 40 00 00 00 00 00
 (543.688454)  can0  602   [8]  23 FF 60 00 BA 03 00 00
 (543.688774)  can0  582   [8]  60 FF 60 00 00 00 00 00
 (543.691742)  can0  601   [8]  23 FF 60 00 68 FA FF FF
 (543.692094)  can0  581   [8]  60 FF 60 00 00 00 00 00
 (543.738954)  can0  602   [8]  23 FF 60 00 BA 03 00 00
 (543.739263)  can0  582   [8]  60 FF 60 00 00 00 00 00
 (543.741596)  can0  601   [8]  23 FF 60 00 68 FA FF FF
 (543.741879)  can0  581   [8]  60 FF 60 00 00 00 00 00
 (543.788360)  can0  602   [8]  23 FF 60 00 BA 03 00 00
 (543.788672)  can0  582   [8]  60 FF 60 00 00 00 00 00
 (543.791458)  can0  601   [8]  23 FF 60 00 68 FA FF FF
 (543.791621)  can0  581   [8]  60 FF 60 00 00 00 00 00
```

デコード:
- `601`/`602` の `40 6C 60 00` → 606C（Velocity actual value）読み取り要求。
  応答 `43 6C 60 00 68 FA FF FF` は node1 の値 `0xFFFFFA68` = -1432（符号付き32bit）。
  応答 `43 6C 60 00 BA 03 00 00` は node2 の値 `0x000003BA` = 954。
- `601`/`602` の `23 FF 60 00 xx xx xx xx` → 60FF（Target velocity）書き込み。
  node1 に `0xFFFFFA68`（-1432）、node2 に `0x000003BA`（954）。応答 `60 FF 60 00`
  は abort ではなく正常応答（先頭バイトが `60`）。
- `409B`（Main power supply current）の読み取りも定期的に流れている。

`/tmp/omsim-pitakuru.jsonl` の最終 state レコード（速度指令を送り続けて
約 40 秒後）:

```json
{
  "sim_time": 611.1,
  "nodes": {
    "1": {"node_id": 1, "state": "operation-enabled", "statusword": 1591,
          "mode": 3, "target_velocity_rpm": -1432.0,
          "command_velocity_rpm": -1432.0,
          "actual_velocity_rpm": -1431.9999999999977,
          "actual_position": -15621192},
    "2": {"node_id": 2, "state": "operation-enabled", "statusword": 1591,
          "mode": 3, "target_velocity_rpm": 954.0,
          "command_velocity_rpm": 954.0,
          "actual_velocity_rpm": 953.9999999999989,
          "actual_position": 10408816}
  }
}
```

両ノードとも `operation-enabled` かつ、それぞれ独立した目標速度
（node1: -1432、node2: +954、単位は 60FF/606C と同じ内部 rpm 表現）に
追従し、`actual_position` が継続して進んでいることを確認した。

単位の整合性確認: pitakuru は `speed [rad/s]` を `rpm2radps` の逆算
（`rpm = speed / 0.10472`）で rpm に変換したうえで `reduction`
（このテストでは `motors.yaml` の設定で 50）を掛けてモータ軸 rpm にし、
さらに `revert: True` で符号反転して `60FF` に書く。実測値と照合:
- motor_id=1, speed=3.0 [rad/s] → 3.0/0.10472 ≈ 28.65 rpm × 50 = 1432.6 →
  revert で符号反転 → **-1432**（実測の 60FF 書き込み値と一致）
- motor_id=2, speed=-2.0 [rad/s] → -2.0/0.10472 ≈ -19.10 rpm × 50 = -954.9 →
  revert で符号反転 → **+954**（実測の 60FF 書き込み値と一致）

## 6. 到達できた地点とできなかったこと

**到達できた:**
- pitakuru の `motor_control_node`（ソース無改造）を、実機 CAN が存在しない
  VM 上で `can0`（vcan）+ omsim（V200 EDS、2 ノード）に接続して正常起動させた
- `enable_all` → 両モータ `operation-enabled` まで遷移させた
- `/motor_control_node/control/velocity` で 2 台に別々の速度指令
  （+3.0 rad/s / -2.0 rad/s）を送り、`60FF` への書き込みと `606C` からの
  読み取りが独立に成立し、omsim 内部の `actual_velocity_rpm` が指令値と
  一致することを確認した
- 速度指令を止めてから `timeout` パラメータ通りに自動 quick stop する
  安全機構の動作も確認した

**できなかった・簡略化した点:**
- vcan は `state UNKNOWN` を返すため、pitakuru の `is_can_interface_up()`
  はそのままでは常に false になる。**この確認では pitakuru_ws を
  変更しない方針を守るため、VM の `/tmp` に置いた一時的な `ip` コマンドの
  シム（`PATH` 差し替え）で回避した。** 実運用や自動テストで毎回この
  vcan 環境を使うのであれば、pitakuru 側の `is_can_interface_up()` の
  判定方法（例えば `ip link show can0` の `NO-CARRIER` フラグの有無で
  見るなど）を見直すか、CI 用に同等のシムを正式に用意する必要がある。
  このタスクでは pitakuru 側のコードは一切変更していない。
- `start_canopen()` の異常系（`can_up()` 失敗時）に `alert_pub` 未初期化で
  落ちる `AttributeError` は pitakuru 側の既存バグとして観測したのみで、
  修正はしていない（`pitakuru_ws` 無改造の方針のため）。
- `4032h` / `6081h` の abort は candump の生フレームではなく Python の
  traceback でのみ確認した（該当セッションの candump ログをその後の
  再起動で上書きしてしまい、生フレームは残っていない）。
- `1016h:01` は実際に abort されたのを確認する前に、静的解析（ソース
  grep）だけを根拠に予防的に omsim へハンドラを追加した。EDS上は
  存在し `rw` だが、pitakuru が実際にこの値をどう使うか（Heartbeat
  producer/consumer 自体は omsim 未実装）は未検証。
- PDO・SYNC・Heartbeat の実消費（`1016h` に書いた値に基づいて実際に
  consumer heartbeat タイムアウト監視をする、等）は omsim 側に実装して
  いない。今回は「値を受理して保持するだけ」で通過させた。

## 7. P2 以降への申し送り（実装優先順位の提案）

今回の実測で判明した「pitakuru の `motor_control_node` が実際に SDO で
触るオブジェクト」の全量（ソース静的解析、`sdo.download`/`sdo.upload`
呼び出し箇所を全て grep）は以下の通り。**タスクブリーフに事前に挙げられて
いたリストには `6081h` が抜けていた**ため、今回追加で判明した。

- download: `1016h:01`, `1017h`（※ `pc_node`＝LocalNode 宛のため CAN には
  出ない）, `4032h`, `6040h`, `6060h`, `6072h`, `6081h`, `6083h`, `6084h`,
  `60FEh:01`, `60FFh`
- upload: `1003h`（sub0, sub1-N）, `409Bh`, `6041h`, `606Ch`

このうち `6040h`, `6041h`, `6060h`, `6072h`(元は abort), `6083h`, `6084h`,
`606Ch`, `60FFh` は元々対応済み。今回 `60FEh:01`, `6072h`, `4032h`,
`6081h`, `1003h`, `409Bh`, `1016h:01` を追加した。**これで pitakuru の
`motor_control_node` が起動〜速度制御に使うオブジェクトは一通り揃った。**

提案する優先順位:

1. **`is_can_interface_up()` 相当の vcan 対応**: pitakuru 側の話だが、
   P7 で自動テストを組む場合はこの判定がボトルネックになる。omsim 側で
   できることは無いため、pitakuru チームへの申し送り事項として残す。
2. **PDO / Heartbeat の実消費**: 今回 `1016h`/`1017h` は「値を保持するだけ」
   で通したが、pitakuru は `start_heartbeat()` で実際に heartbeat 監視に
   依存している可能性がある（未検証）。P3 で Heartbeat consumer/producer
   を実装する際に、pitakuru の実際の依存度を再確認する価値がある。
3. **`6072h`/`4032h` のトルク制限を `MotorPlant` に反映**: 現状は値を
   保持するだけで実際のトルク制限としては機能していない。P4/P6 で
   トルク・アラームモデルを拡張する際に統合する。
4. **`60FEh` の Physical outputs の意味付け**: pitakuru は
   quick_stop や free_off のたびに特定のビットパターン
   （`\x00\x00\x10\x01`, `\x00\x00\x40\x01` 等）を書き込んでいる。
   これが HWTO（動力遮断）や励磁 OFF と対応するのであれば、P5 の
   HWTO 実装時に意味付けを検討する。

## 8. コミット

```
git add docs/pitakuru-connection.md scripts/run_with_pitakuru.sh \
  docs/oriental_motor/BLVD-KRD_CANopen_V200.eds \
  docs/oriental_motor/BLVD-KBRD_CANopen_V300.eds \
  omsim/driver/model.py
git -c user.name="Kousuke Takeuchi" commit -m "..."
```
