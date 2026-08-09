# P8 ストアードデータ運転 / FW-RV 運転 / I/O 原点復帰 実装計画

ベース: master `b192105`（P7 完了、623 テスト passed）
ブランチ: `feature/p8-stored-fwrv`

P5 以降ずっと送り続けてきた「残りの運転方式」を実装する。

---

## 仕様で確認済みの事実（推測しないこと）

### 入力信号の割付 No.（HP-5141J 14-1 実測）

ネットワークから信号を割り付けるときは信号名ではなく**割付 No.** を使う。

| No. | 信号 | No. | 信号 | No. | 信号 |
|---|---|---|---|---|---|
| 0 | 未使用 | 32 | **START** | 52/53 | FW-JOG-P / RV-JOG-P |
| 1 | FREE | 33 | SSTART | 56/57 | FW-POS / RV-POS |
| 2 | S-ON | 35 | NEXT | 58/59 | FW-SPD / RV-SPD |
| 3 | CLR | 36 | **HOME** | 60/61 | FW-PSH / RV-PSH |
| 4 | QSTOP | 40-47 | M0-M7 | 64/65 | USR-LAT-IN0 / IN1 |
| 5 | STOP | 48/49 | **FW-JOG / RV-JOG** | 66/67 | FW-BLK / RV-BLK |
| 8 | ALM-RST | 50/51 | FW-JOG-H / RV-JOG-H | 68/69/70 | FW-LS / RV-LS / HOMES |
| 9 | P-PRESET | 18 | TRQ-LMT | 80-95 | D-SEL0-15 |
| 24 | PLOOP-MODE | 19 | SPD-LMT | 96-127 | R0-R31 |

### R-IN 機能選択は MEXE02 専用（実測）

`R-IN0 機能選択` の NET-ID は **17408（4400h）**、既定 `2:S-ON`。以降 R-IN1=17409…と続く。
netid が `0x1000` 以上なので **CANopen のメーカ固有領域 4000h-4FFFh には収まらず、
EDS にも存在しない**（= SDO では触れない。MEXE02 / mxex だけで設定する）。

現在の mxex ローダは `index = 0x4000 + netid` で機械的に写しているため、
これらを「未知の index」として数えている。**「CANopen に対応する index が無い
（MEXE02 専用）」と区別して報告する**よう直す。

### 既定の R-IN 割付（HP-5143E 60FEh 実測、P5 で実装済み）

R-IN0-7 = S-ON / PLOOP-MODE / TRQ-LMT / CLR / QSTOP / STOP / FREE / ALM-RST、
R-IN8-15 = D-SEL0-7。**START も JOG も既定では割り付いていない**ため、
ストアードデータ運転や FW/RV 運転を CANopen 越しに動かすには
R-IN の機能割付を変える必要がある（= mxex 経由）。

### 運転方式（P5 Task 1 で表を作成済み）

`omsim/driver/operation_type.py`。ストアードデータ運転も同じ表を使う。

---

## Global Constraints

P7 と同じ。開始時点で **623 テスト passed**。

---

## Task 1: R-IN / R-OUT の機能割付

**Files:** Create `omsim/driver/io_functions.py` / Modify `omsim/driver/model.py`,
`omsim/apps/mxex.py` / Test `tests/unit/test_io_functions.py`

- `INPUT_FUNCTIONS`（割付 No. → 信号名）/ `OUTPUT_FUNCTIONS`
- `DriverModel.remote_input_assignment`（R-IN0-15 の割付 No.、既定は実測どおり）
- `DriverModel.set_remote_input_function(slot, number)`（mxex から設定する口）
- `DriverModel.remote_signal(name)`（「S-ON が入っているか」を名前で引く）
- **P5 で入れた `R_IN_*` の固定ビット参照を、この割付表経由に置き換える**
- mxex ローダ: netid ≥ 0x1000 は「MEXE02 専用（CANopen 非対応）」として数え、
  R-IN/R-OUT 機能選択は実際に適用する

- [ ] Step 1-5: TDD → コミット `feat: R-IN/R-OUT の機能割付を実装する`

## Task 2: 運転データ（ストアードデータ）のテーブル

**Files:** Create `omsim/driver/operation_data.py` / Modify `omsim/driver/model.py` /
Test `tests/unit/test_operation_data.py`

- 運転データ No. 0-63（実機は 256 だが、まず 64 で作り、上限は定数で持つ）
- 1 件 = 運転方式 / 位置 / 速度 / 加速レート / 減速レート / トルク制限値
- `403Dh`（NET selection data number）と D-SEL0-7 の合成で選択
- 読み書きは mxex とテスト用 API から（CANopen 側の運転データ R/W は netid 空間なので
  SDO では触れない。**触れないことを README と `--list-stubs` に明記する**）

- [ ] Step 1-5: TDD → コミット `feat: ストアードデータ運転の運転データテーブルを追加する`

## Task 3: ストアードデータ運転（START / SSTART / NEXT）

**Files:** Modify `omsim/driver/model.py` / Test `tests/unit/test_stored_operation.py`

- START の立ち上がりで、選択中の運転データ No. の運転を開始
- 運転方式はダイレクトデータ運転と同じ実行系（`_start_direct_motion`）を共有する
- 運転中の START は無視（実機は「運転中運転起動」パラメータ次第。**既定の
  無視のみ実装し、パラメータは未実装として明示**）

- [ ] Step 1-5: TDD → コミット `feat: ストアードデータ運転 (START) を実装する`

## Task 4: FW/RV 運転（JOG / インチング / 連続運転）

**Files:** Modify `omsim/driver/model.py` / Test `tests/unit/test_fwrv_operation.py`

- `FW-JOG` / `RV-JOG`: 押している間だけ JOG 速度で回る
- `FW-JOG-P` / `RV-JOG-P`: 立ち上がりで 1 回だけインチング（移動量ぶん）
- `FW-SPD` / `RV-SPD`: 押している間だけ連続運転（速度制御）
- 速度・加減速は「JOG 運転速度」等のパラメータ（netid 空間）を model 属性として持つ

- [ ] Step 1-5: TDD → コミット `feat: FW/RV 運転 (JOG・インチング・連続運転) を実装する`

## Task 5: I/O 原点復帰運転（HOME 信号）

**Files:** Modify `omsim/driver/model.py` / Test `tests/unit/test_io_homing.py`

- `HOME` 信号の立ち上がりで原点復帰。方式は `4160h`（(HOME) 原点復帰モード、
  現在 passthrough）で選ぶ
- 2 センサ方式 / 1 方向回転方式 / 押し当て方式のうち、**hm モードで実装済みの
  センサ探索ロジックを共有できるものだけ**実装し、残りは明示的に未実装とする

- [ ] Step 1-5: TDD → コミット `feat: I/O 原点復帰運転を実装する`

## Task 6: 総仕上げ

- [ ] README・`--list-stubs`・網羅率の実測記録
- [ ] デモシナリオ（mxex で START を割り付けてストアード運転）
- [ ] 3 回連続テスト・最終レビュー・master マージ

---

## 意図的に対象外

- WRAP 系・押し当て系の運転方式（`operation_type.py` の表で未実装として abort）
- モーション拡張モード
- シーケンス機能・運転データの結合方式・運転 I/O イベント
- 運転データ R/W コマンドの CANopen 経由アクセス（netid 空間のため SDO では不可）
