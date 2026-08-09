# P7 シナリオランナー本格版 / replay / CI 実装計画

ベース: master `8db36e7`（P6 完了、591 テスト passed）
ブランチ: `feature/p7-report-replay-ci`

設計書 11 節の P7 は「シナリオランナー本格版（`report.html` / `junit.xml`）、CI、3D ビュー、replay」。
3D ビューは P3.5 で、`junit.xml` は P0 で完了済み。残りを実装する。

---

## 現状（実測）

- `omsim/apps/scenario.py` は `StepResult(index, kind, ok, detail)` を返し、`--junit` で
  JUnit XML を書ける。**所要時間も実測値も残らない**ため、失敗したとき何が起きたか
  レポートから追えない。
- `Recorder` は `jsonl` に `{"kind": "frame", ...}` と `{"kind": "state", "snapshot": ...}`
  を書ける（`--record`）。**読み戻す口が無い**。
- CI は無い（`.github/workflows` が存在しない）。

---

## Global Constraints

P6 と同じ。開始時点で **591 テスト passed**。CI では新規依存を増やさない。

---

## Task 1: シナリオ結果に実測を残す

**Files:** Modify `omsim/apps/scenario.py` / Test `tests/unit/test_scenario_report.py`

- `StepResult` に `seconds`（所要時間）と `actual`（`expect` の実測値）を足す
- `write_junit` に `time` 属性を出す
- 既存の `--junit` の出力は壊さない（属性追加のみ）

- [ ] Step 1-5: TDD → コミット `feat: シナリオ結果に所要時間と実測値を残す`

## Task 2: `report.html` の生成

**Files:** Modify `omsim/apps/scenario.py` / Test `tests/unit/test_scenario_report.py`

- `--report report.html` で自己完結した HTML を書く（外部参照なし）
- 各ステップの PASS/FAIL・種別・所要時間・実測値
- 失敗ステップには、その前後の CAN フレーム（`--record` があれば）を添える
- **CAN ログが無いときは「無い」と書く**（あるように見せない）

- [ ] Step 1-5: TDD → コミット `feat: シナリオの report.html を生成する`

## Task 3: replay（記録の読み戻しと再生）

**Files:** Create `omsim/sim/replay.py`, `omsim/web/static/replay.js` /
Modify `omsim/web/app.py`, `omsim/web/static/*` /
Test `tests/unit/test_replay.py`, `tests/unit/test_web_replay.py`

- `load_recording(path)` → `{"frames": [...], "states": [...]}`（壊れた行は数えて報告）
- `omsim --replay <jsonl> --web-port 8080` で**シミュレーションを動かさずに**記録を再生
- Web 側は再生位置スライダと再生/停止（既存の 4 ペインをそのまま使う）

- [ ] Step 1-5: TDD → 実ブラウザ確認 → コミット `feat: 記録した jsonl を Web で再生できるようにする`

## Task 4: CI（GitHub Actions）

**Files:** Create `.github/workflows/ci.yml` / Test `tests/unit/test_ci_workflow.py`

- Ubuntu ランナーで `sudo modprobe vcan` → `scripts/setup_vcan.sh` → `pytest`
- Python は 3.8（VM と揃える）。依存は `requirements.txt` の pin をそのまま使う
- **vcan が使えない環境で黙って skip しない**こと（skip 0 を CI でも守る）
- ワークフロー YAML の妥当性をテストで検査する（構文と必須ステップの存在）

- [ ] Step 1-5: TDD → コミット `feat: GitHub Actions で vcan つきのテストを回す`

## Task 5: 総仕上げ

- [ ] README（`--report` / `--replay` / CI の説明）
- [ ] 網羅率の実測記録・3 回連続テスト
- [ ] 最終ブランチレビュー → 修正 → master マージ

---

## 意図的に対象外

- ストアードデータ運転 / FW-RV 運転 / I/O 原点復帰運転（P5 から送ったまま。別フェーズ）
- 記録の巻き戻し再生中に SDO を受け付ける（replay は読み取り専用）
