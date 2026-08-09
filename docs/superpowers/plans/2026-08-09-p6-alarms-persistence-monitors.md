# P6 アラーム全コード / 永続化 / モニタ・メンテナンスコマンド 実装計画

ベース: master `c8431a1`（P5 完了、549 テスト passed）
ブランチ: `feature/p6-alarms-monitors`

---

## 仕様で確認済みの事実（推測しないこと）

### アラームコードと EMCY（HP-5143E 4.5 実測）

**メーカ固有アラームの EMCY コードは `0xFF00 | アラームコード`、error register は `81h`。**
通信系のみ CiA301 標準コード（`8110h` CAN overrun / `8120h` error passive /
`8130h` node guarding・heartbeat / `8140h` Bus-Off 復帰 / `8210h` PDO 長さエラー、
いずれも error register `11h`）。

全 42 コード（実測どおり）:

| code | 名前 | code | 名前 |
|---|---|---|---|
| 10h | Position deviation | 55h | Electromagnetic brake connection error |
| 20h | Overcurrent | 60h | ±LS both sides active |
| 21h | Main circuit overheat | 61h | Reverse ±LS connection |
| 22h | Overvoltage | 62h | Return-to-home operation error |
| 25h | Undervoltage | 63h | No HOMES |
| 26h | Motor overheat | 64h | Z, SLIT signal error |
| 28h | Encoder error | 66h | Hardware overtravel |
| 29h | Internal circuit error | 67h | Software overtravel |
| 2Ah | Encoder communication error | 68h | HWTO input detection |
| 30h | Overload | 6Ah | Return-to-home additional operation error |
| 31h | Overspeed | 70h | Operation data error |
| 41h | EEPROM error | 71h | Unit setting error |
| 42h | Initial encoder error | 81h | Network bus error |
| 44h | Encoder EEPROM error | 84h | RS-485 communication error |
| 45h | Motor combination error | 85h | RS-485 communication timeout |
| 4Ah | Return-to-home incomplete | 8Ch | Outside setting range |
| 50h | Electromagnetic brake overcurrent | F0h | CPU error |
| 53h | HWTO input circuit error | F3h | CPU overload |

**現状の実装は過負荷アラームに `2310h`（CiA301 の汎用コード）を使っており、
実測した表の `FF30h` と食い違っている。** P6 で是正する。

ALM-RST 入力による解除可否とモーターの励磁挙動は HP-5141J 8 章「1-2 アラーム一覧」実測:
`20h`/`28h`/`29h` などは**解除不可**、`10h`/`21h`/`25h`/`26h` は**減速後無励磁**で解除可、
`22h` などは**即無励磁**。

### 永続化（HP-5143E 1010h / 1011h 実測）

- `1010h:01` に **"save"**（`73h 61h 76h 65h` = `0x65766173`）を書くと全パラメータ保存。
  `1010h:02` は通信パラメータ（`1000h`-`1FFFh`）のみ。
- `1011h:01` に **"load"**（`0x64616F6C`）を書くと既定値へ復帰。`1011h:02` は通信のみ。
- 署名が違うときは **abort `0800002xh`**、保存/復帰に失敗したら **abort `06060000h`**。
- 読み出しは保存機能の情報を返す。

### モニタ（HP-5143E 実測）

`404Bh`-`4050h` はユーザー単位のモニタ（目標/指令/実位置、目標/指令/実速度）、
`4073h` 位置偏差 / `4075h` 速度偏差、`406Bh` トルク / `406Ch` 負荷率 / `406Dh` 累積負荷 /
`4078h` 過負荷率、`407Ah`/`407Fh` トリップメータ、`407Eh` オドメータ、
`409Bh` 主電源電流 / `409Ch`-`409Fh` 電力量 / `40A1h` 総稼働時間 / `40A2h` 起動回数 /
`40A3h` インバータ電圧 / `40A4h` 主電源電圧 / `40A9h` 連続稼働時間、`4056h` 現在の通信エラー。

---

## Global Constraints

P5 と同じ。開始時点で **549 テスト passed**。

---

## Task 1: アラームコード表

**Files:** Create `omsim/driver/alarm_codes.py` / Modify `omsim/driver/alarm_model.py`,
`omsim/driver/model.py` / Test `tests/unit/test_alarm_codes.py`

- `ALARM_CODES`（code → 名前・リセット可否・励磁挙動）
- `emcy_for(code)` = `0xFF00 | code`、`error_register_for(code)` = `0x81`
- 通信系 EMCY（`8110h`/`8120h`/`8130h`/`8140h`/`8210h`）は別テーブル
- **過負荷の EMCY を `2310h` から `FF30h` へ是正**（既存テストも直す）
- `inject_alarm` はコードから EMCY を自動で決める口を持つ

- [ ] Step 1-5: TDD → コミット `fix: アラーム全コードの表を追加し過負荷の EMCY を FF30h に是正する`

## Task 2: 永続化（1010h / 1011h）

**Files:** Modify `omsim/driver/model.py` / Test `tests/unit/test_persistence.py`

- 署名 "save" / "load" のみ受け付け、それ以外は abort `08000020h`
- `sub1` = 全パラメータ、`sub2` = 通信パラメータ（`1000h`-`1FFFh`）のみ
- 保存内容はプロセス内に持つ（実機の不揮発メモリ相当。ファイルには書かない）
- `1011h` の復帰は「新しい `DriverModel` の既定値」を正とする

- [ ] Step 1-5: TDD → コミット `feat: パラメータの保存/既定値復帰 (1010h/1011h) を実装する`

## Task 3: モニタ系オブジェクト

**Files:** Modify `omsim/driver/model.py` / Test `tests/unit/test_monitors.py`

- ユーザー単位モニタ `404Bh`-`4050h`
- 偏差 `4073h`/`4075h`、負荷率 `406Ch`/`4078h`（モデルが持つトルクから算出）
- 稼働時間系 `40A1h`/`40A9h`/`40A2h`、走行距離系 `407Eh`/`407Fh`/`407Ah`
- **モデルが持っていない量（電圧・温度・電力量）は 0 を返すだけのスタブとして
  理由付きで登録する**（黙って 0 を返さない）

- [ ] Step 1-5: TDD → コミット `feat: モニタ系オブジェクトを実装する`

## Task 4: メンテナンスコマンド

**Files:** Modify `omsim/driver/model.py` / Test `tests/unit/test_maintenance.py`

- `40C2h` アラーム履歴クリア、`40C5h` P-PRESET（現在位置を原点にする）、
  `40D7h`/`40D8h` トリップメータクリア、`40D6h` ユーザー電力量クリア
- `40C6h` Configuration（設定反映）、`40CDh`/`40CEh`/`40D3h` クリア系
- 実行トリガは「1 を書いたら実行、読み出しは 0」という既存の `40C0h` と同じ形

- [ ] Step 1-5: TDD → コミット `feat: メンテナンスコマンドを実装する`

## Task 5: Web のアラームモニタ / I/O モニタ

**Files:** Modify `omsim/driver/model.py`（snapshot）, `omsim/web/static/*` /
Test `tests/unit/test_web_static.py`, `tests/unit/test_web_app.py`

- アラームモニタ: 現在アラーム（コード + 名前）と履歴（`1003h` のパック値を分解して表示）
- I/O モニタ: R-IN / R-OUT の各ビットをランプ表示（既定機能名つき）

- [ ] Step 1-5: TDD → 実ブラウザ確認 → コミット `feat: Web にアラームモニタと I/O モニタを追加する`

## Task 6: 総仕上げ

- [ ] README・網羅率の実測記録・3 回連続テスト
- [ ] 最終ブランチレビュー → 修正 → master マージ

---

## 意図的に対象外（P7 以降）

- ストアードデータ運転 / FW-RV 運転 / I/O 原点復帰運転（P5 から送ったもの）
- 電圧・温度・電力量の物理モデル（値を返す口だけ作り、中身はスタブ）
- 過負荷アラームの検出時間特性（負荷率に応じた検出時間カーブ）
