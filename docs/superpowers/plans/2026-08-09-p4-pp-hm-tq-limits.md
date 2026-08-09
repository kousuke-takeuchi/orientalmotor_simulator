# P4 pp / hm / tq モード・停止動作・option code・リミット・touch probe 実装計画

ベース: master `4fddd65`（P3.5 完了、405 テスト passed）
ブランチ: `feature/p4-modes`
実行環境: Vagrant VM。`ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && <cmd>"`

---

## 仕様で確認済みの事実（推測しないこと）

すべて `pdftotext -layout` による HP-5143E 実測。

### Controlword / Statusword（モードごとにビットの意味が変わる）

| ビット | pv（実装済み） | pp（7.3.3/7.3.4） | tq（7.4.3/7.4.4） | hm（7.5.3/7.5.4） |
|---|---|---|---|---|
| CW 4 | – | NSP: New set point | 予約 | HOS: Homing operation start |
| CW 5 | – | IMM: Change set immediately | 予約 | 予約 |
| CW 6 | – | REL: 0=絶対 / 1=相対 | 予約 | 予約 |
| CW 8 | HALT | HALT | HALT（6087h の torque slope で停止） | HALT |
| CW 9 | – | COSP: **未サポート。0 固定** | 予約 | 予約 |
| SW 10 | Target reached | Target reached | Target reached | Target reached |
| SW 11 | ILA | ILA | ILA | ILA |
| SW 12 | pv: Speed is 0 | **SPA: Set point acknowledge** | 予約 | **HA: Homing attained** |
| SW 13 | – | **ERROR: Following error** | 予約 | **HE: Homing error** |
| SW 15 | – | TLC | TLC | TLC |

- pp の set-point ハンドシェイク: `NSP(bit4)` 0→1 で位置決め開始、`SPA(bit12)`=1 で受理中、
  処理が終わって次の set-point を待てる状態になったら `SPA`=0。
- `IMM(bit5)`=1 なら運転中の新しい set point を即時反映、0 なら現在の位置決め完了後に開始
  （1 段だけ保持する「Set of set-points」）。
- `ILA(bit11)` が立つ条件: ソフトウェアリミット / FW-LS・RV-LS / FW-BLK・RV-BLK /
  STOP・QSTOP・CLR。
- **Remote(bit9) が 0 のときは Quick stop / Fault reset / Halt 以外の Controlword は無効。**

### option code（605Ah-605Eh）

| index | 名前 | 範囲（既定） | 値の意味 |
|---|---|---|---|
| 605Ah | Quick stop option code | −3〜6（**2**） | −3: 4736h の時間で減速し quick-stop-active に留まる / −2: 4735h のレートで減速し留まる / −1: 即時停止し留まる / 0: 即時停止して switch-on-disabled / 1: slow down ramp で switch-on-disabled / 2: quick stop ramp(6085h) で switch-on-disabled / 5: slow down ramp で留まる / 6: quick stop ramp で留まる |
| 605Bh | Shutdown option code | 0〜1（**0**） | 0: 即時停止して ready-to-switch-on / 1: slow down ramp |
| 605Ch | Disable operation option code | 0〜1（**1**） | 0: 即時停止して switched-on / 1: slow down ramp |
| 605Dh | Halt option code | 0〜1（**1**） | 0: 予約 / 1: slow down ramp（tq ではトルク制限値を除く） |
| 605Eh | Fault reaction option code | 0〜2（**2**） | 0: 即時停止・無励磁 / 1: slow down ramp / 2: quick stop ramp(6085h) |

現状の実装は `605Ah` を「値の保持のみ（常に既定動作）」としてスタブ登録している。

### ソフトウェアリミット（607Dh）

- sub1 = Min position limit、sub2 = Max position limit（INT32、既定 0）。
- **有効になるのは homing 完了後**。
- 次のときは無効: `Min ≥ Max`、または Min/Max がともに 0。
- 内部では home offset(`607Ch`) を引いた値と比較する
  （corrected limit = limit − home offset）。

### homing（6098h / 6099h / 609Ah / 607Ch）

- `6098h` Homing method: −1〜37（既定 **37**）。サポートは
  1 / 2 / 8 / 12 / 17 / 18 / 24 / 28 / 35 / 37 / −1。**35 と 37 は同じ動作（現在位置を原点にする）**。
- `6099h` Homing speeds: sub1 = switch 探索速度（既定 60）、sub2 = zero 探索速度（既定 30）。
  ※ PDF の表は sub0/sub1 と誤記されているが、`00h` は Highest sub-index。EDS で実値を確認すること。
- `HOS(CW bit4)` 1 で開始、`HA(SW bit12)` で完了、`HE(SW bit13)` でエラー。

### touch probe（60B8h-60BDh / 60D5h-60D8h）

このフェーズでは **60B8h/60B9h と 60BAh-60BDh の値保持＋ラッチ**まで。
トリガ源（DIN）の割付は P5 の CN4 I/O 実装に依存するため、ラッチのトリガは
`DriverModel.trigger_touch_probe(probe, edge)` という内部 API で受ける。

---

## Global Constraints

P3.5 と同じ（Python 3.8 / 依存追加なし / `omsim/driver/` は can・canopen 非依存 /
未実装は `--list-stubs` に出す / コミットは日本語・AI 署名なし / LF / VM 経由実行 /
テスト前に `pgrep -af 'omsim.apps'`）。開始時点で **405 テスト passed**。

---

## Task 1: 停止動作と option code 群（605Ah-605Eh）

**Files:** Create `omsim/driver/stopping.py` / Modify `omsim/driver/model.py`,
`omsim/driver/state_machine.py` / Test `tests/unit/test_stopping.py`,
`tests/unit/test_driver_option_codes.py`

**Interfaces:**
- `StopAction(kind, ramp)` — `kind` は `"immediate"` / `"slow_down"` / `"quick_stop_ramp"` /
  `"custom_rate"` / `"custom_time"`、`stay_in_state` を持つ
- `resolve_quick_stop(code)` / `resolve_shutdown(code)` / `resolve_disable_operation(code)` /
  `resolve_halt(code)` / `resolve_fault_reaction(code)` → `StopAction`
- `DriverModel` が `605Ah`-`605Eh` を実装（`605Ah` のスタブ登録を外す）

### なぜこれをやるか

pp / tq / hm はどれも「停止のしかた」を option code に従って変える。先に停止動作を
一箇所へ集約しておかないと、モードごとに同じ分岐を書き散らすことになる。

- [ ] Step 1: 失敗するテストを書く（表の全値を網羅。範囲外は abort）
- [ ] Step 2-4: 実装。`quick-stop-active` に留まる系（−3/−2/−1/5/6）と抜ける系（0/1/2）の
      差を `stay_in_state` で表し、`state_machine.stop_completed()` の呼び出し可否に反映する
- [ ] Step 5: コミット `feat: 停止動作と option code 群 (605Ah-605Eh) を実装する`

## Task 2: pp モード（Profile Position）

**Files:** Modify `omsim/driver/operation.py`, `omsim/driver/model.py` /
Test `tests/unit/test_operation_pp.py`, `tests/unit/test_driver_pp.py`

**Interfaces:**
- `ProfilePositionMode`（`operation.py`）— `MODE_CODE = 1`
- `607Ah` Target position / `6081h` Profile velocity / `6082h` End velocity /
  `60F2h` Positioning option code（relative option / rotary axis direction option のみ）
- Statusword bit12 = SPA、bit10 = Target reached、bit13 = Following error

- [ ] Step 1: 失敗するテストを書く
  - 絶対位置決め: `607Ah` を書いて `NSP` 0→1 で動き出し、到達で `TR`=1
  - `SPA` のハンドシェイク（受理で 1、完了で 0）
  - 相対位置決め（`REL`=1）は現在位置からの移動量
  - `IMM`=1 は運転中に即時差し替え、`IMM`=0 は 1 段保持して完了後に開始
  - `HALT`=1 で `605Dh` に従って減速停止し `TR`=1（停止したという意味）
  - Remote(bit9)=0 のときは NSP が無効
- [ ] Step 2-4: 実装。既存の `TrapezoidProfile` を速度指令生成に流用し、位置制御は
      「残距離から目標速度を決める」台形位置決めとして実装する
- [ ] Step 5: コミット `feat: pp (Profile Position) モードを実装する`

## Task 3: tq モード（Profile Torque）

**Files:** Modify `omsim/driver/operation.py`, `omsim/driver/motor_plant.py`,
`omsim/driver/model.py` / Test `tests/unit/test_operation_tq.py`

- `6071h` Target torque / `6074h` Torque demand / `6087h` Torque slope / `6072h` Max torque
- `HALT` は torque slope で 0 へ落とす
- `TLC`（SW bit15）が `6072h` / `4032h` の制限に当たったら立つ

- [ ] Step 1-5: TDD → コミット `feat: tq (Profile Torque) モードを実装する`

## Task 4: hm モード（Homing）

**Files:** Modify `omsim/driver/operation.py`, `omsim/driver/model.py` /
Test `tests/unit/test_operation_hm.py`

- `6098h`（35/37 = 現在位置を原点、17/18 = リミットセンサ、24/28 = HOME センサ）
- `6099h` sub1/sub2、`609Ah` Homing acceleration、`607Ch` Home offset
- `HOS`(CW bit4) で開始、`HA`(SW bit12) / `HE`(SW bit13)
- センサ入力は `DriverModel.set_limit_inputs(fw_ls, rv_ls, home)` で受ける
  （CN4 の実配線は P5）

- [ ] Step 1-5: TDD → コミット `feat: hm (Homing) モードを実装する`

## Task 5: ソフトウェアリミットとリミットセンサ

**Files:** Modify `omsim/driver/model.py` / Test `tests/unit/test_limits.py`

- `607Dh` sub1/sub2、`607Ch` Home offset、有効化条件（homing 完了後・Min<Max）
- `60FDh` bit0 NLS / bit1 PLS / bit2 HS を実配線
- リミット到達で `ILA`(SW bit11) を立て、停止する

- [ ] Step 1-5: TDD → コミット `feat: ソフトウェアリミットとリミットセンサを実装する`

## Task 6: touch probe

**Files:** Modify `omsim/driver/model.py` / Test `tests/unit/test_touch_probe.py`

- `60B8h` Touch probe function / `60B9h` Touch probe status /
  `60BAh`-`60BDh` ラッチ値 / `60D5h`-`60D8h` カウンタ
- トリガは `DriverModel.trigger_touch_probe(probe, edge)`

- [ ] Step 1-5: TDD → コミット `feat: touch probe (60B8h-60BDh) を実装する`

## Task 7: 総仕上げ

- [ ] Web のステータス表示をモード別ビット名に対応させる（pp なら bit12=SPA 等）
- [ ] シナリオ `tests/scenarios/pp_demo.yaml` / `hm_demo.yaml`
- [ ] README・網羅率の実測記録・実ブラウザ確認・3 回連続テスト
- [ ] 最終ブランチレビュー → 修正 → master マージ

---

## 完了条件

- [ ] 全テスト passed（SKIP 0）を 3 回連続
- [ ] pp / tq / hm が `6060h` の切替で動き、`6061h` に反映される
- [ ] Statusword のビットがモードごとに正しい意味を持つ（bit12/13 が pv/pp/hm で別物）
- [ ] option code 605Ah-605Eh が全値で仕様どおりに効く
- [ ] ソフトウェアリミットが homing 完了後にだけ有効になる
- [ ] `omsim --coverage` の実測を台帳に記録

## 意図的に対象外

- メーカ固有運転（ダイレクトデータ / ストアード / FW-RV / I/O 原点復帰）は P5
- CN4 の I/O 割付（DIN/DOUT/R-I/O 機能選択）は P5
- `60F2h` の Change immediately option / Request-response option / IP option（**仕様上サポート外**）
- Following error の実際の検出（位置偏差の閾値）は P6（`6065h`/`6066h` 未実装のため）
