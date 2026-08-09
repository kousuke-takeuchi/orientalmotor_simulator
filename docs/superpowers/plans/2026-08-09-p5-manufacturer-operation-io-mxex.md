# P5 メーカ固有運転 / CN4 I/O / mxex ローダ 実装計画

ベース: master `5695e1d`（P4 完了、490 テスト passed）
ブランチ: `feature/p5-manufacturer`
実行環境: Vagrant VM。`ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && <cmd>"`

設計書 11 節の P5 は「メーカ固有運転（ダイレクトデータ / ストアード / FW-RV / I/O 原点復帰）、
CN4 I/O + HWTO、mxex ローダ + アドレスコード表抽出 + diff ツール」。HWTO は P3.5 で完了済み。

---

## 仕様で確認済みの事実（推測しないこと）

### 運転方式（HP-5141J 3-4 実測。ダイレクト/ストアード共通）

| 値 | 運転方式 | 本計画 |
|---|---|---|
| 0 | 減速停止（指定した運転プロファイルに従う） | 実装 |
| 1 | 絶対位置決め | 実装 |
| 2 | 相対位置決め（指令位置基準） | 実装 |
| 3 | 相対位置決め（検出位置基準） | 実装 |
| 4-6 | 相対位置決め（目標位置基準）/ 相対位置決め速度制御 | 未実装（abort） |
| 7 | 連続運転（位置制御） | 未実装（abort） |
| 8-15 | WRAP 系 | 未実装（abort。41CAh WRAP 設定も値の保持のみ） |
| 16 | 連続運転（速度制御） | 実装 |
| 17-23 | 押し当て / トルク制御 / サイクリック速度制御 | 未実装（abort） |
| 32 (20h) | 即停止 | 実装 |
| 31 (1Fh) / 39 / 48-51 | 減速停止（動作中プロファイル）/ モーション拡張モード | 未実装（abort） |

### ダイレクトデータ運転（HP-5141J 4 章 実測）

- 「データの書き換えと運転の開始を同時に行なう」モード。
- 反映トリガ `4033h`: **上位 16bit = ライフタイム / 下位 16bit = 反映トリガ**。
  どちらかが範囲外なら「設定範囲外」の通信エラーで**上位下位とも反映しない**。
- 反映トリガ下位 16bit が `0` = 起動しない、`1`（`2`/`3` も同じ）= 通常起動（ユーザー単位）、
  `4`-`19` = 単位指定起動（速度/加減速の単位を変える変種）。
  **同じ値を書いた場合は起動しない。**
- 「ダイレクトデータ運転トリガ自動クリア」パラメータが有効（**初期値：有効**）のとき、
  起動の成否によらず反映トリガ（下位 16bit）は自動で `0` に戻る。
- 負の値（例: `-4` = 速度）は「その項目を書いた瞬間に反映する」個別トリガ。
- 運転には S-ON（励磁）が必要。

### 関連オブジェクト（EDS 実測）

`402Ch` 運転データ No. / `402Dh` 運転方式 / `402Eh` 位置 / `402Fh` 速度 /
`4030h` 加速レート / `4031h` 減速レート / `4032h` トルク制限値 / `4033h` トリガ /
`4034h` 転送先、`403Eh` Driver input command / `403Fh` Driver output status、
`404Bh`-`4050h` ユーザー単位のモニタ、`40C5h` P-PRESET、`40C6h` Configuration。

### アドレスコード（HP-5141J 7 章「アドレスコード一覧」実測）

`NET-ID` 列が mxex の `netid` に対応する。P3.5 で動力遮断まわり（400/401/408-411）を
`docs/oriental_motor/address-codes.md` に確定済み。本計画で **パラメータ R/W コマンドの
13-1〜13-17 の表を機械的に抽出**して同ファイルへ広げる。

---

## Global Constraints

P4 と同じ。開始時点で **490 テスト passed**。

---

## Task 1: 運転方式（OperationType）の共通定義

**Files:** Create `omsim/driver/operation_type.py` / Test `tests/unit/test_operation_type.py`

- `OPERATION_TYPES`（値 → 名前）と `SUPPORTED_OPERATION_TYPES`
- `resolve_operation_type(value)` → 未対応値は `NotImplementedObjectError`、範囲外は `ObjectAccessError`
- ダイレクト運転とストアード運転で同じ表を使う（値の意味が 2 か所に割れないように）

- [ ] Step 1-5: TDD → コミット `feat: メーカ固有運転の運転方式テーブルを追加する`

## Task 2: ダイレクトデータ運転

**Files:** Create `omsim/driver/direct_data.py` / Modify `omsim/driver/model.py`,
`omsim/driver/operation.py` / Test `tests/unit/test_direct_data.py`

- `4033h` の上位/下位分解、範囲外は両方とも反映しない、同値の再書き込みは起動しない、
  トリガ自動クリア（既定有効）
- 運転方式 0/1/2/3/16/32 の実行（位置決めは pp の台形位置決めを再利用）
- `402Ch`-`4032h` の保持と反映
- S-ON（励磁）でないときは起動しない

- [ ] Step 1-5: TDD → コミット `feat: ダイレクトデータ運転を実装する`

## Task 3: CN4 I/O（Driver input command / Driver output status / 60FEh）

**Files:** Modify `omsim/driver/model.py` / Test `tests/unit/test_driver_io.py`

- `403Eh` Driver input command: S-ON / FREE / STOP などのリモート入力ビット
- `403Fh` Driver output status: SON-MON / ALM-B / IN-POS などの出力ビット
- `60FEh` Digital outputs を実配線（現在はスタブ）
- ビット割付は HP-5141J「入力信号一覧 / 出力信号一覧」を実測してから書く

- [ ] Step 1-5: TDD → コミット `feat: CN4 のリモート I/O (403Eh/403Fh/60FEh) を実装する`

## Task 4: アドレスコード表の抽出

**Files:** Create `scripts/extract_address_codes.py` /
Modify `docs/oriental_motor/address-codes.md` / Test `tests/unit/test_address_codes.py`

- HP-5141J の `pdftotext -layout` 出力から「NET-ID / 名称 / 設定範囲 / 初期値」を抽出
- 抽出結果を Markdown 表として `address-codes.md` に追記
- 抽出できなかった行は**黙って捨てず**件数を報告する

- [ ] Step 1-5: TDD → コミット `feat: アドレスコード表を PDF から抽出する`

## Task 5: mxex ローダと diff ツール

**Files:** Create `omsim/apps/mxex.py` / Modify `omsim/apps/omsim_main.py` /
Test `tests/unit/test_mxex_loader.py`

- `--mxex <file>` で起動時にパラメータを適用（`NodeSpec.mxex` は既に存在）
- 対応表にある netid だけを適用し、**未知の netid は件数を warning に出す**
- `omsim --mxex-diff a.mxex b.mxex` で 2 ファイルの差分を出す
- 現在の `warn_ignored_mxex()`（読み飛ばし警告）を置き換える

- [ ] Step 1-5: TDD → コミット `feat: mxex ローダと diff ツールを追加する`

## Task 6: 総仕上げ

- [ ] README・`omsim --coverage` の実測記録
- [ ] デモシナリオ `tests/scenarios/direct_data_demo.yaml`
- [ ] 実ブラウザ確認・3 回連続テスト
- [ ] 最終ブランチレビュー → 修正 → master マージ

---

## 意図的に対象外（P6 以降）

- ストアードデータ運転（運転データ R/W コマンド、シーケンス機能、運転 I/O イベント）
- FW/RV 運転（JOG / 高速 JOG / インチング）
- I/O 原点復帰運転（3 センサ / 2 センサ / 1 方向回転 / 押し当て）
- WRAP 系・押し当て系の運転方式、モーション拡張モード
- ダイレクトデータ運転のライフタイム監視（値の保持と範囲検査のみ）
