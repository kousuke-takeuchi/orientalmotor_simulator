# P3 PDO / SYNC / エラー制御 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RPDO/TPDO 4+4 の動的マッピングと transmission type、SYNC producer/consumer、Heartbeat consumer、node guarding、`1003h` エラー履歴の是正を実装する。あわせて、P2 最終レビューで「PDO のテストを書く前に片付けないと書き直しコストが跳ね上がる」と指摘された 4 件の技術的負債（CommandQueue の再設計・トリガ種別・送信フレームの CAN ログ化・validate_object の軽量化）を先に返済する。

**Architecture:** 前半（Task 1-5）で土台を直す。CommandQueue を `(index, sub)` 単位の last-write-wins + `maxlen` にし、同期/非同期の適用タイミングを表す `trigger` を持たせ、自ノードの送信フレームを CAN ログに載せ、SDO 検証の deepcopy を軽量化し、残っていた Minor 債務をまとめて払う。後半（Task 6-12）で PDO 通信パラメータ・マッピングパラメータ・RPDO 受信・TPDO 送信・SYNC・Heartbeat consumer・node guarding・`1003h` を実装する。最後の Task 13 で Web への反映を確認する。

PDO/SYNC/node guarding/Heartbeat consumer の実際のフレーム送受信は、`canopen.LocalNode` の `tpdo`/`rpdo`/`pdo` （`canopen.pdo` サブモジュール）が SDO クライアント経由の read/save を前提にした設計であり、この案件のような「同一プロセス内でローカルに信頼できる」ローカルノードの使い方とは噛み合わないため使わない。代わりに、既存の `Recorder.FrameListener`（`can.Listener` を直接使う）と同じパターンで、`omsim/node/realtime_bridge.py` に専用の `can.Listener` を実装する。PDO の値のエンコード/デコードは、ビット演算を自前で書かず `canopen` の `ObjectDictionary` 由来の `ODVariable.encode_raw()`/`decode_raw()` をそのまま使う（符号付き整数の扱いを間違えないため）。BLVD-KRD の既定マッピングはすべてバイト境界に揃っているため、本フェーズはバイト境界マッピングのみをサポート対象とする（ビット単位のサブバイトパッキングは対象外、根拠は Task 6 に記載）。

**Tech Stack:** Python 3.8 / canopen 2.4.1 / python-can 4.5.0（socketcan）

**前提となる文書:**
- 設計書: `docs/superpowers/specs/2026-08-08-oriental-motor-simulator-design.md`（5.1 節が通信層の網羅スコープ）
- P2 計画: `docs/superpowers/plans/2026-08-09-p2-web-visualization.md`（書式のお手本）
- 進捗台帳: `.git/sdd/progress.md`
- EDS: `docs/oriental_motor/BLVD-KRD_CANopen_V400.eds`（PDO パラメータの既定値の正本）
- 仕様書: `docs/oriental_motor/HP-5143E.pdf` 4.2（NMT Error Control）/ 4.4（SYNC）/ 4.7（PDO）/ Object Dictionary 節（inhibit time・event timer の単位）

## 仕様で確認済みの事実（推測しないこと）

`pdftotext -layout` で実測済み。単位・値の意味を以下に固定する。

- **inhibit time（180xh:03h）**: 単位は **100 μs**。既定値 50 = 5ms。「値が変化してから最後の送信より前に inhibit time が経過していること」が送信条件の一部（PDO Object Dictionary 節 p76 実測）。
- **event timer（180xh:05h）**: 単位は **ms**。既定値 0（無効）。「event timer で定義される最大送信間隔」。
- **guard time（100Ch）**: 単位は **ms**。**life time factor（100Dh）**: 単位なし（乗数）。life time = guard time × life time factor。node guarding の生死判定はマスタ側の責務であり、スレーブ（omsim）はパラメータの保持と RTR 応答のみ行う（4.2.1 実測: 「A remote node error is indicated through the NMT service node guarding event IF the RTR is not confirmed within the guard time...」の主語は NMT master）。
- **1005h COB-ID SYNC message**: bit30 = SYNC producer 有効化、bits0-10 = 11bit COB-ID、既定 `0x80`。
- **1006h Communication cycle period**: 単位は **μs**。既定 0（SYNC producer 無効）、範囲 0-1,000,000。
- **RPDO transmission type**（4.7.2 実測）: `0x00`=SYNC 受信時に反映、`0xFE`=即時反映（RTR 発行・node lifetime リセットを伴う、firmware 2.02 以降）、`0xFF`=即時反映。この3値のみサポート。
- **TPDO transmission type**（4.7.2 実測）: `0x00`=値が変化していれば次の SYNC で送信、`0x01`-`0xF0`=n 回目の SYNC ごとに送信、`0xF1`-`0xFB`=予約（設定不可）、`0xFC`=SYNC 受信時にサンプルし RTR 受信時に送信、`0xFD`=RTR 受信時にサンプルして送信、`0xFE`/`0xFF`=変化後に inhibit time 経過で送信、または event timer 経過で送信。予約値・未対応値への変更は SDO abort `0x06090030`。
- **COB-ID sub1 のビット**（Object Dictionary 1400h/1800h 実測）: bit31=VALID（0=有効/1=無効）、bit30=RTR（TPDO のみ有効、0=RTR 許可/1=RTR 禁止、RPDO では常に 0 固定=ZERO）、bits0-10=11bit COB-ID、bits11-29=ZERO 固定。COB-ID が有効な間（bit31=0 の間）は COB-ID を変更してはならない。
- **PDO マッピングの変更手順**（4.7.1 実測）: ①該当 PDO を bit31=1 で無効化 → ②対応するマッピングパラメータの sub0 を 0 にして無効化 → ③sub1-4 を書き換え → ④sub0 に個数を書いて有効化 → ⑤PDO を bit31=0 で再度有効化。
- **node guarding 応答**（4.2.1 実測）: RTR 要求は COB-ID `700h+NodeID`、データ長 0。応答は同じ COB-ID、データ 1 バイト = `(toggle<<7) | NMT状態コード`（toggle は応答ごとに反転、初回 0）。NMT 状態コード: Operational=5、Stopped=4、Pre-operational=127(0x7F)。
- **EMCY エラーコード表**（4.5 実測、抜粋）: `8130h`（error_register `11h`）= "Node guarding error or heartbeat error"。Heartbeat consumer のタイムアウトはこのコードを使う。

## Global Constraints

- Python は **3.8**。3.9 以降の構文（`list[int]` の実行時評価、`dict | dict`、`match`）を使わない。型注釈は `typing` から import する。
- 依存は完全に pin する: `canopen==2.4.1` / `python-can==4.5.0` / `pytest==8.3.5` / `PyYAML==6.0.2` / `fastapi==0.124.4` / `uvicorn==0.33.0` / `httpx==0.28.1` / `websockets==13.1`。新規依存は追加しない。
- **`omsim/driver/` 配下は `can` と `canopen` を import してはならない。** 層の依存規則は `tests/unit/test_layering.py` が全方向で自動検証する（`apps → web,sim,node,can,driver` / `web → sim,driver` / `sim → node,can,driver` / `node → driver`（+ canopen は node のみ許可）/ `can → なし`（+ canopen は can のみ許可）/ `driver → なし`）。
- **複数ノードを 1 プロセスで同時に動かす。** 状態はインスタンス変数のみに持つ。`ObjectRouter` は状態を持たない。
- シミュレーションのステップは **1ms 固定**（`SimClock.STEP_SECONDS = 0.001`）。
- **未実装の挙動を黙って既定値で答えない。** 未実装は `omsim --list-stubs` に必ず現れること。
- **git commit に Claude / AI の署名や言及を一切入れない。コミットメッセージは日本語で書く。**
- ファイルは改行 **LF** で保存する。
- **VM の共有フォルダ経由でファイルを保存する。scp で VM に直接置かない。**
- **テスト実行前に `pgrep -af 'omsim.apps'` で残骸プロセスが無いか確認する**（vcan 上の二重ノードが flaky の原因。`vcan_available` フィクスチャがプリフライト検査するが、それでも疑わしければ手動確認する）。
- 実行コマンドは VM 経由の実物を書く: `cd /c/Users/ktake/code/keisuu/oriental_motor_simulator && ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest ..."`
- 開始時点で **270 テスト passed**。

---

## ファイル構成

| ファイル | 責務 | 状態 |
|---|---|---|
| `omsim/sim/command_queue.py` | `CommandQueue`。last-write-wins + maxlen + trigger | 変更 |
| `omsim/sim/recorder.py` | `Recorder`（ロック）、`attach_recorder`（tx ログ） | 変更 |
| `omsim/driver/model.py` | PDO パラメータ・SYNC・Heartbeat consumer・node guarding の OD 窓口を追加、`validate_object` 軽量化 | 変更 |
| `omsim/driver/pdo.py` | PDO 通信/マッピングパラメータのビット表現（can/canopen 不使用） | 新規 |
| `omsim/driver/alarm_model.py` | `raise_alarm` が 1003h 用のパック済みコードを履歴に積む、`EMCY_HEARTBEAT_ERROR` 追加 | 変更 |
| `omsim/driver/errors.py` | `ABORT_NO_DATA` 追加 | 変更 |
| `omsim/node/realtime_bridge.py` | RPDO 受信・TPDO 送信・SYNC 送受信・node guarding 応答・Heartbeat consumer 受信の配線 | 新規 |
| `omsim/sim/sync_counter.py` | CAN スレッド → step() への SYNC 受信通知 | 新規 |
| `omsim/sim/manager.py` | `RealtimeBridge`/`SyncCounter` の配線、`od` を node_id ごとに保持 | 変更 |
| `omsim/apps/omsim_main.py` | `--web-host` 既定を `127.0.0.1` に変更 | 変更 |
| `tests/integration/test_multi_node.py` | `RESPONSE_TIMEOUT` リテラルを定数に寄せる | 変更 |

---

## Task 1: CommandQueue を `(index, sub)` 単位の last-write-wins + maxlen にする

**Files:**
- Modify: `omsim/sim/command_queue.py`
- Modify: `tests/unit/test_command_queue.py`

**Interfaces:**
- Consumes: `DriverModel.write_object(index, sub, value)`
- Produces:
  - `CommandQueue(maxlen=64)`
  - `.put(index, sub, value)` — 同じ `(index, sub)` への再書込みは最後の値だけを残す
  - `.pending_count()`
  - `.drain(model)` — 従来と同じシグネチャのまま（trigger は Task 2 で追加）

### なぜこれをやるか

現在の `CommandQueue` は無制限の `deque` で、同じオブジェクトへの複数回書込みをすべて溜め込む。PDO では生産者（CAN 受信スレッド）が消費者（1kHz の `step()`）を追い越しうる。RPDO を 1ms 未満の間隔で複数回受信すると、現在の実装は全件を順に適用するため実機と結果は一致するが、キューが際限なく伸びる（メモリリークではないが、遅延の蓄積を招く）。実機は「1 制御周期に同じ Controlword が複数回届いたら最後だけが効く」ため、**最新値だけを保持する**のが仕様的にも正しい。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_command_queue.py` の `test_drain_applies_in_order` を次のように置き換える（意味が「順序どおり全部適用される」から「同じキーは最後の値だけが残る」に変わるため）:

```python
def test_same_key_keeps_only_the_last_value():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 100)
    queue.put(0x6083, 0, 200)
    assert queue.pending_count() == 1
    queue.drain(model)
    assert model.read_object(0x6083) == 200
    assert queue.pending_count() == 0


def test_different_keys_are_both_applied():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 300)
    queue.put(0x6084, 0, 400)
    assert queue.pending_count() == 2
    queue.drain(model)
    assert model.read_object(0x6083) == 300
    assert model.read_object(0x6084) == 400
```

`test_is_safe_across_threads` を、同じキーへの多重書込みが最終的に 1 件へ収束することを確認する形に置き換える:

```python
def test_is_safe_across_threads():
    queue = CommandQueue()
    model = DriverModel(node_id=1)

    def producer():
        for value in range(1, 201):
            queue.put(0x6083, 0, value)

    threads = [threading.Thread(target=producer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # 全スレッドが同じ (0x6083, 0) に書くため、last-write-wins で 1 件に収束する。
    assert queue.pending_count() == 1
    queue.drain(model)
    assert queue.pending_count() == 0
    assert 1 <= model.read_object(0x6083) <= 200
```

末尾に maxlen のテストを追加する:

```python
def test_maxlen_evicts_the_oldest_distinct_key():
    queue = CommandQueue(maxlen=2)
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 100)   # 1 件目
    queue.put(0x6084, 0, 200)   # 2 件目、上限ちょうど
    queue.put(0x605A, 0, 0)     # 3 件目、上限超過 -> 最古 (0x6083) を破棄
    assert queue.pending_count() == 2
    queue.drain(model)
    # 0x6083 への書込みは破棄されたので既定値のまま
    assert model.read_object(0x6083) == 1000
    assert model.read_object(0x6084) == 1000
    assert model.read_object(0x605A) == 2


def test_maxlen_is_not_consumed_by_updates_to_the_same_key():
    queue = CommandQueue(maxlen=2)
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 100)
    queue.put(0x6083, 0, 200)   # 同じキーの更新は新しい枠を消費しない
    queue.put(0x6084, 0, 300)
    assert queue.pending_count() == 2
    queue.drain(model)
    assert model.read_object(0x6083) == 200
    assert model.read_object(0x6084) == 300
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_command_queue.py -q 2>&1 | tail -20"`
Expected: `test_same_key_keeps_only_the_last_value` と `test_maxlen_*` が FAIL（現在の `CommandQueue` は `deque` で全件保持し `maxlen` 引数も無い）。

- [ ] **Step 3: 実装する**

`omsim/sim/command_queue.py`（全面置き換え）:

```python
"""CAN 受信スレッドからシミュレーションループへ書込みを渡すキュー。

python-can の Notifier は専用スレッドでコールバックを呼ぶため、SDO/PDO の
書込みをその場で DriverModel に適用すると step() と競合する。実機の
ドライバは受信したコマンドを次の制御周期の先頭で適用するので、同じ形に
そろえる。

PDO では生産者 (CAN 受信スレッド) が消費者 (1kHz の step()) を追い越し
うる。実機は同じオブジェクトへの複数回書込みは最後の値だけが効くため、
(index, sub) ごとの last-write-wins で保持する。無制限に溜め続けると
遅延が蓄積するため、上限を超えたら最も古い書込み (異なるキー) を破棄し
warning ログを出す (黙って捨てない)。

読み出しはキューを通さない。副作用が無く、1ms 待たせると SDO の
タイムアウトを招くため。
"""
import collections
import logging
import threading

logger = logging.getLogger(__name__)

QueuedWrite = collections.namedtuple("QueuedWrite", ["index", "sub", "value"])

DEFAULT_MAXLEN = 64


class CommandQueue(object):
    def __init__(self, maxlen=DEFAULT_MAXLEN):
        self._lock = threading.Lock()
        self._maxlen = maxlen
        # (index, sub) -> QueuedWrite。挿入順は OrderedDict のキー順で保つ
        # (異なるキー間の適用順序を保存するため)。同じキーへの再書込みは
        # 一度削除してから append し直し、最新の書込みを最後尾に置く。
        self._items = collections.OrderedDict()

    def put(self, index, sub, value):
        key = (index, sub)
        with self._lock:
            if key in self._items:
                del self._items[key]
            elif len(self._items) >= self._maxlen:
                oldest_key, oldest = next(iter(self._items.items()))
                del self._items[oldest_key]
                logger.warning(
                    "CommandQueue が上限 %d 件を超えたため、最古の書込み "
                    "%04Xh:%02X=%s を破棄しました",
                    self._maxlen, oldest.index, oldest.sub, oldest.value,
                )
            self._items[key] = QueuedWrite(index, sub, value)

    def pending_count(self):
        with self._lock:
            return len(self._items)

    def drain(self, model):
        """溜まった書込みを順に適用し、発生した例外の一覧を返す。

        1 件が失敗しても後続を捨てない。捨てると「マスタは書けたつもり
        なのにシミュレータが受け取っていない」という追跡困難な状態になる。
        """
        with self._lock:
            items = list(self._items.values())
            self._items.clear()

        errors = []
        for item in items:
            try:
                model.write_object(item.index, item.sub, item.value)
            except Exception as err:
                errors.append((item, err))
        return errors
```

- [ ] **Step 4: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_command_queue.py -v"`
Expected: 全 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed（270 件から純増分だけ増える）

- [ ] **Step 5: コミット**

```bash
git add omsim/sim/command_queue.py tests/unit/test_command_queue.py
git commit -m "fix: CommandQueue を (index,sub) 単位の last-write-wins + maxlen にする"
```

---

## Task 2: CommandQueue にトリガ種別（immediate/sync）を追加する

**Files:**
- Modify: `omsim/sim/command_queue.py`
- Modify: `tests/unit/test_command_queue.py`

**Interfaces:**
- Consumes: Task 1 の `CommandQueue`
- Produces:
  - `QueuedWrite = namedtuple("QueuedWrite", ["index", "sub", "value", "trigger"])`
  - `.put(index, sub, value, trigger="immediate")` — `trigger` は `"immediate"` または `"sync"`
  - `.drain(model, sync_received=False)` — `trigger="sync"` の項目は `sync_received=True` の回だけ適用し、それ以外はキューに残す

### なぜこれをやるか

同期 RPDO（transmission type `0x00`）は「SYNC 受信時に反映」が仕様であり、非同期（`0xFE`/`0xFF`）は「即時反映」が仕様（4.7.2 実測）。現在のキューには「いつ適用するか」の概念が無く、SYNC を表現できない。Task 8（RPDO 受信）で使う。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_command_queue.py` の末尾に追加:

```python
def test_immediate_trigger_is_applied_every_drain():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 500, trigger="immediate")
    queue.drain(model, sync_received=False)
    assert model.read_object(0x6083) == 500


def test_sync_trigger_waits_for_sync_received():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 600, trigger="sync")
    queue.drain(model, sync_received=False)
    assert model.read_object(0x6083) == 1000  # まだ既定値のまま
    assert queue.pending_count() == 1

    queue.drain(model, sync_received=True)
    assert model.read_object(0x6083) == 600
    assert queue.pending_count() == 0


def test_sync_and_immediate_can_coexist_in_the_same_drain():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 700, trigger="sync")
    queue.put(0x6084, 0, 800, trigger="immediate")
    queue.drain(model, sync_received=False)
    assert model.read_object(0x6083) == 1000  # sync 待ち
    assert model.read_object(0x6084) == 800   # immediate は即時反映
    assert queue.pending_count() == 1


def test_default_trigger_is_immediate():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 900)  # trigger 省略
    queue.drain(model)         # sync_received 省略
    assert model.read_object(0x6083) == 900
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_command_queue.py -q 2>&1 | tail -20"`
Expected: `trigger` を受け付けず `TypeError` で FAIL

- [ ] **Step 3: 実装する**

`omsim/sim/command_queue.py` の変更点:

```python
QueuedWrite = collections.namedtuple("QueuedWrite", ["index", "sub", "value", "trigger"])
```

`put`:

```python
    def put(self, index, sub, value, trigger="immediate"):
        key = (index, sub)
        with self._lock:
            if key in self._items:
                del self._items[key]
            elif len(self._items) >= self._maxlen:
                oldest_key, oldest = next(iter(self._items.items()))
                del self._items[oldest_key]
                logger.warning(
                    "CommandQueue が上限 %d 件を超えたため、最古の書込み "
                    "%04Xh:%02X=%s を破棄しました",
                    self._maxlen, oldest.index, oldest.sub, oldest.value,
                )
            self._items[key] = QueuedWrite(index, sub, value, trigger)
```

`drain`:

```python
    def drain(self, model, sync_received=False):
        """溜まった書込みのうち、今回適用すべきものだけを取り出して適用する。

        trigger="immediate" は毎回適用する。trigger="sync" は
        sync_received=True の回だけ適用し、そうでなければキューに残して
        次の SYNC まで待つ。
        """
        with self._lock:
            ready = []
            remaining = collections.OrderedDict()
            for key, item in self._items.items():
                if item.trigger == "sync" and not sync_received:
                    remaining[key] = item
                else:
                    ready.append(item)
            self._items = remaining

        errors = []
        for item in ready:
            try:
                model.write_object(item.index, item.sub, item.value)
            except Exception as err:
                errors.append((item, err))
        return errors
```

- [ ] **Step 4: テストを通し、Task 1 の呼び出し元と整合させる**

`omsim/sim/manager.py::step()` はまだ `sync_received` を渡していないため既定値 `False` で動くが、これは Task 10（SYNC）で正しく配線する。今の時点では **SDO 経由の書込みは常に `trigger="immediate"`** のままであることを確認する（`omsim/node/od_bridge.py` の `queue.put(index, subindex, value)` は `trigger` を省略しているため既定の `"immediate"` になる）。

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_command_queue.py -v"`
Expected: 全 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed

- [ ] **Step 5: コミット**

```bash
git add omsim/sim/command_queue.py tests/unit/test_command_queue.py
git commit -m "feat: CommandQueue にトリガ種別 (immediate/sync) を追加する"
```

---

## Task 3: 送信フレームを CAN ログに記録する

**Files:**
- Modify: `omsim/sim/recorder.py`
- Test: `tests/integration/test_recorder_attach.py`（追記）または新規結合テスト

**Interfaces:**
- Consumes: `canopen.Network`（`network.bus`）
- Produces: `attach_recorder(network, recorder, clock)` が、受信フレームに加えて **自ノードの送信フレームも `direction="tx"` で記録する**

### なぜこれをやるか

SocketCAN は `receive_own_messages` が既定 `False` のため、omsim 自身が送信したフレーム（SDO 応答・boot-up・Heartbeat・EMCY、そして P3 で追加する PDO・SYNC・node guarding 応答）は、受信専用の `FrameListener` には一切届かない。**P3 の中身は全部 tx 側**（TPDO 送信・SYNC producer・node guarding 応答）なので、このままでは新機能が Web の CAN ログに 1 つも映らない。

送信経路は `network.send_message()`（NMT/EMCY/Heartbeat/今回追加する PDO・SYNC・node guarding）と canopen 内部の SDO サーバ応答の両方があり、最終的にどちらも `network.bus.send()` を通る。個別の送信箇所ごとに `recorder.frame("tx", ...)` を書いて回ると、将来の送信経路追加のたびに記録漏れが起きる。そのため **`network.bus.send` を 1 箇所だけラップする**（送信元コードは一切変更しない）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_recorder_attach.py` の末尾に追記（このファイルは現在ユニットテストのみのため、末尾に vcan 結合テストを追加する。ファイル冒頭に `import pytest` と `pytestmark = pytest.mark.vcan` が無ければ追加せず、下記テスト関数にのみ `@pytest.mark.vcan` を付ける）:

```python
@pytest.mark.vcan
def test_own_transmitted_frames_are_recorded_as_tx(vcan_available):
    from omsim.can.bus import close_network, open_network
    from omsim.sim.clock import SimClock

    recorder = Recorder(None)
    clock = SimClock(realtime=False)
    network = open_network(channel=vcan_available)
    attach_recorder(network, recorder, clock)
    try:
        # NMT boot-up と同じ経路 (network.send_message) で 1 フレーム送る。
        network.send_message(0x701, [0])
        import time
        time.sleep(0.1)
        tx_frames = [f for f in recorder.recent_frames() if f["dir"] == "tx"]
        assert any(f["can_id"] == 0x701 and f["data"] == "00" for f in tx_frames)
    finally:
        close_network(network)
        recorder.close()
```

（`vcan_available` フィクスチャを使うため `tests/integration/` 配下に置く。既存の `test_recorder_attach.py` が `tests/unit/` にある場合は、この関数だけ `tests/integration/test_recorder_tx_over_vcan.py` として新規作成する。**どちらに置いたか報告書に明記すること**。）

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/integration -k tx_are_recorded -q 2>&1 | tail -20"`
Expected: FAIL（tx フレームが記録されない）

- [ ] **Step 3: 実装する**

`omsim/sim/recorder.py` の `attach_recorder` を変更する:

```python
def attach_recorder(network, recorder, clock):
    listener = FrameListener(recorder, clock)
    network.listeners.append(listener)
    notifier = getattr(network, "notifier", None)
    if notifier is not None:
        # python-can 4.5.0 の Notifier は __init__ で listeners のコピーを取るため、
        # connect() 後に network.listeners へ append しただけでは効かない。
        notifier.add_listener(listener)
    _wrap_bus_send_for_tx_logging(network, recorder, clock)
    return listener


def _wrap_bus_send_for_tx_logging(network, recorder, clock):
    """自ノードの送信フレームも CAN ログに載せる。

    SocketCAN は receive_own_messages が既定 False のため、Notifier
    (受信側) には自分の送信が返ってこない。SDO 応答・boot-up・
    Heartbeat・EMCY、そして P3 で追加する PDO・SYNC・node guarding
    応答は全て最終的に network.bus.send() を通るため、送信元コードを
    個別に触らず、この 1 箇所をラップするだけで将来の送信経路追加にも
    自動的に追従する。
    """
    bus = network.bus
    if getattr(bus, "_omsim_tx_wrapped", False):
        return
    original_send = bus.send

    def send_and_record(msg, *args, **kwargs):
        original_send(msg, *args, **kwargs)
        if not getattr(msg, "is_remote_frame", False):
            recorder.frame("tx", msg.arbitration_id, bytes(msg.data), clock.now)

    bus.send = send_and_record
    bus._omsim_tx_wrapped = True
```

- [ ] **Step 4: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/integration -k tx_are_recorded -v"`
Expected: PASS

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed。**特に `tests/integration/test_bootup_over_vcan.py` が引き続き通ること**（boot-up は既にマスタ役の別ネットワークで観測しており、tx ラップの有無に依存しない設計だが、二重記録などの副作用が無いか確認する）

- [ ] **Step 5: コミット**

```bash
git add omsim/sim/recorder.py tests/integration/test_recorder_attach.py
git commit -m "feat: 自ノードの送信フレームを network.bus.send のラップで CAN ログに記録する"
```

---

## Task 4: `validate_object` の deepcopy を軽量化する

**Files:**
- Modify: `omsim/driver/model.py`
- Test: `tests/unit/test_driver_model.py`（追記）

**Interfaces:**
- Consumes: なし
- Produces: `DriverModel.validate_object(index, sub, value)` の内部実装のみ変更（外向きの挙動は不変）

### なぜこれをやるか

現在 `validate_object` は SDO 書込みごとに `copy.deepcopy(self)` して writer を試走させている。`DriverModel` は `state_machine` / `units` / `profile` / `plant` / `alarms` / `operation` の 6 個の入れ子オブジェクトを持ち、deepcopy は毎回これら全部を再帰的に複製する。PDO の頻度（RPDO は最短で 1ms ごとに変化しうる）ではこの検証コストが無視できなくなる。

**検証ロジックを別に書くと writer と重複してずれる**ため、writer 自体は変えない。代わりに、実際に writer が変更しうる入れ子オブジェクトだけを選んで deepcopy し、それ以外は shallow copy で共有する「部分的な使い捨てコピー」に変える。

現在の全 writer を確認すると、変更されるのは次の 2 系統だけである:
- `_write_controlword`（`6040h`）: `self.state_machine.write_controlword()` と `self._sync_excited()`（`self.plant.excited` を書く）
- `_write_alarm_reset`（`40C0h`）: `self.alarms.reset()` と `self.state_machine.set_fault(False)`

他の writer はすべて `DriverModel` 自身のスカラー属性（`self.target_velocity_rpm` など）を書くだけで、shallow copy で自動的に独立になる。Task 6-11 で PDO パラメータの writer を追加するが、これらも `self.rpdo_comm[i]` などの新しいインスタンス属性（リストの中身は個別オブジェクト）を書き換えるため、対象に追加する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_driver_model.py` の末尾に追記:

```python
def test_shadow_isolation_holds_for_every_registered_writer():
    """全 writer について、現在の値で validate_object しても実モデルは一切変化しない。

    すでに legal な値を書き戻すだけなので値の妥当性チェックは常に通り、
    writer 内部の副作用 (state_machine の遷移や alarms のリセット等) だけが
    実モデルに漏れていないかを機械的に確認できる。軽量化した _shadow() の
    対象リストに漏れがあれば、このテストが実モデルの変化として検出する。
    """
    from omsim.driver.errors import ObjectAccessError
    from omsim.driver.model import DriverModel

    model = DriverModel(node_id=1)
    model.state_machine.step(0.001)
    model.write_object(0x6040, 0, 0x0006)
    model.write_object(0x6040, 0, 0x0007)
    model.write_object(0x6040, 0, 0x000F)

    def deep_state():
        return (
            model.state_machine.statusword,
            model.state_machine.controlword,
            model.plant.excited,
            model.plant.position,
            model.alarms.active_alarm,
            tuple(model.alarms.history),
            tuple(sorted(model.passthrough_values.items())),
        )

    before = deep_state()
    for index, sub in sorted(DriverModel.router._writers):
        try:
            current = model.read_object(index, sub)
        except ObjectAccessError:
            continue
        try:
            model.validate_object(index, sub, current)
        except ObjectAccessError:
            continue
        assert deep_state() == before, (
            "{:04X}h:{:02X} の validate_object が実モデルを変化させた".format(index, sub))


def test_validate_object_still_isolates_controlword_side_effects():
    from omsim.driver.model import DriverModel

    model = DriverModel(node_id=1)
    model.validate_object(0x6040, 0, 0x0006)
    assert model.state_machine.controlword == 0  # 検証だけでは実モデルは動かない
```

- [ ] **Step 2: テストを実行して現状を確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_driver_model.py -q 2>&1 | tail -20"`
Expected: 現在の実装（フル deepcopy）でも意味的には通るはず（PASS）。**もし落ちたら、それは現状の deepcopy 版にも既に隔離漏れがあるということなので、軽量化より先にその原因を報告書に記録すること。**

- [ ] **Step 3: `_shadow()` を実装し `validate_object` を置き換える**

`omsim/driver/model.py` の `DriverModel` クラスに追加（`validate_object` の直前）:

```python
    # validate_object の使い捨てコピーで deepcopy する対象。
    # writer が実際に変更しうる入れ子オブジェクト/コンテナのみを列挙する。
    # 新しい writer が別の入れ子オブジェクトを触るようになったら追記すること
    # (test_shadow_isolation_holds_for_every_registered_writer が検出する)。
    _SHADOW_DEEP_ATTRS = (
        "state_machine", "plant", "alarms", "passthrough_values",
        "rpdo_comm", "rpdo_mapping", "tpdo_comm", "tpdo_mapping",
    )

    def _shadow(self):
        """validate_object 用の使い捨てコピーを作る。

        copy.deepcopy(self) は state_machine/plant/profile/units/operation/
        alarms など全ての入れ子オブジェクトを再帰的に複製するため、PDO の
        書込み頻度では重すぎる (P2 最終レビュー指摘)。writer が実際に
        変更するのは _SHADOW_DEEP_ATTRS の 8 個だけで、profile・units・
        operation は writer から直接変更されない (target_velocity_rpm 等は
        DriverModel 自身のスカラー属性であり、shallow copy で自動的に
        独立になる)。そのため shallow copy + 上記だけを個別に deepcopy する。
        """
        shadow = copy.copy(self)
        for name in self._SHADOW_DEEP_ATTRS:
            setattr(shadow, name, copy.deepcopy(getattr(self, name)))
        return shadow
```

`validate_object` を置き換える:

```python
    def validate_object(self, index, sub=0, value=0):
        """index:sub に value を書き込めるかどうかだけを判定する（実体は書き換えない）。

        CAN 受信スレッド (od_bridge.on_write) が、キューに積む前に SDO の
        abort 応答を正しく返せるようにするための窓口。writer ハンドラの中
        には 40C0h のアラームリセットのように副作用を伴うものがあるため、
        「検証専用のロジックを別に書く」のではなく、writer ハンドラ自体を
        使い捨てコピー (_shadow()) 上で実際に走らせ、例外が出るかどうかで
        判定する。これなら検証ロジックと適用ロジックが二重に書かれてずれる
        ことがない。コピー側に生じた副作用はコピーごと捨てるため、呼び出し
        元の状態には一切影響しない。

        受け付けられない場合は ObjectAccessError（NotImplementedObjectError
        を含む）を投げる。
        """
        self.router.write(self._shadow(), index, sub, value)
```

**注意**: Task 6-9 で `self.rpdo_comm` 等の属性を `DriverModel.__init__` に追加するまでは `_SHADOW_DEEP_ATTRS` にあるこれらの名前は未定義のため `getattr` が `AttributeError` になる。**この Task の時点では `_SHADOW_DEEP_ATTRS` から `"rpdo_comm", "rpdo_mapping", "tpdo_comm", "tpdo_mapping"` を除外しておき、Task 6/7 でこれらの属性を追加するのと同じコミットで `_SHADOW_DEEP_ATTRS` に追記する。**

- [ ] **Step 4: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_driver_model.py -v"`
Expected: 全 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed（`test_od_bridge.py::test_validate_object_rejects_alarm_reset_without_running_its_side_effects` を含む）

- [ ] **Step 5: コミット**

```bash
git add omsim/driver/model.py tests/unit/test_driver_model.py
git commit -m "perf: validate_object の deepcopy を実際に変更される入れ子だけに絞って軽量化する"
```

---

## Task 5: 積み残りの Minor 債務を返済する

**Files:**
- Modify: `tests/integration/test_multi_node.py`
- Modify: `omsim/sim/recorder.py`
- Modify: `omsim/apps/omsim_main.py`
- Modify: `omsim/web/app.py`
- Modify: `omsim/sim/clock.py`
- Test: `tests/unit/test_omsim_cli.py`（変更）
- Test: `tests/unit/test_clock.py`（追記）
- Test: `tests/unit/test_recorder.py`（追記）

**Interfaces:**
- Consumes: なし
- Produces: 4 件の独立した修正（1 コミットにまとめる。相互依存が無いため）

### なぜこれをやるか

P2 最終レビューの Minor 指摘のうち、後続タスクをブロックしない軽微な 4 件をまとめて片付ける（`_read_error_field` と 1003h のメーカ固有コード問題は Task 12 でまとめて直す）。

- [ ] **Step 1: `RESPONSE_TIMEOUT` リテラルを定数へ寄せる**

`tests/integration/test_multi_node.py` の 136 行目付近:

```python
        node.sdo.RESPONSE_TIMEOUT = 1.0
```

を、`tests/integration/test_sdo_over_vcan.py` と同じ定数へ変更する:

```python
        node.sdo.RESPONSE_TIMEOUT = SDO_RESPONSE_TIMEOUT
```

ファイル冒頭の import に追加:

```python
from omsim.apps.scenario import SDO_RESPONSE_TIMEOUT
```

- [ ] **Step 2: `Recorder._buffer` をロックで保護する**

`omsim/sim/recorder.py` の `Recorder` を変更する（`FrameListener`（CAN 受信スレッド）と uvicorn の WebSocket 送信ループ（別スレッド）の両方から `frame()`/`recent_frames()` が呼ばれるため）:

```python
class Recorder(object):
    def __init__(self, path, buffer_size=2000):
        self._handle = open(path, "w", encoding="utf-8") if path else None
        self._buffer = collections.deque(maxlen=buffer_size)
        self._lock = threading.Lock()

    def frame(self, direction, can_id, data, sim_time):
        record = {
            "kind": "frame",
            "t": sim_time,
            "dir": direction,
            "can_id": can_id,
            "data": bytes(data).hex(),
            "text": describe_frame(can_id, data),
        }
        with self._lock:
            self._buffer.append(record)
        self._write(record)

    def recent_frames(self, limit=100):
        with self._lock:
            items = list(self._buffer)
        return items[-limit:]
```

（`state`/`close`/`_write` は変更不要。`_write` はファイルハンドルへの書込みのみで、`self._handle` を差し替えるコードが無いためロック不要。）

ファイル冒頭に `import threading` を追加する。

`tests/unit/test_recorder.py` の末尾に追記:

```python
def test_frame_and_recent_frames_are_safe_across_threads():
    import threading

    from omsim.sim.recorder import Recorder

    recorder = Recorder(None)

    def producer(offset):
        for i in range(200):
            recorder.frame("bus", 0x700 + offset, bytes([i % 256]), 0.0)

    threads = [threading.Thread(target=producer, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # クラッシュ (例外) しないことと、直近 limit 件が取れることを確認する。
    frames = recorder.recent_frames(limit=50)
    assert len(frames) == 50
    recorder.close()
```

- [ ] **Step 3: Web の既定バインドを `127.0.0.1` に変更する**

`omsim/apps/omsim_main.py`:

```python
    parser.add_argument("--web-host", default="127.0.0.1")
```

`omsim/web/app.py` の `run_web`:

```python
def run_web(hub, host="127.0.0.1", port=8080):
```

`tests/unit/test_omsim_cli.py` の `test_web_host_defaults_to_all_interfaces` を次に置き換える:

```python
def test_web_host_defaults_to_localhost():
    assert parse_args([]).web_host == "127.0.0.1"
```

**README への影響**: Task 13 で Web の使い方を書く際、VM の IP からブラウザで見る手順には明示的に `--web-host 0.0.0.0` を指定する形で記載する（この Task では README は変更しない）。

- [ ] **Step 4: `SimClock.advance` の busy loop を解消する**

`omsim/sim/clock.py` の `advance`:

```python
    def advance(self):
        self.tick_count += 1
        if self.realtime:
            target = self._wall_start + self.now
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                # 遅延している間 sleep を一切呼ばないと、シミュレーション
                # ループが完全な busy loop になって GIL を独占し続け、
                # CAN 受信スレッドや uvicorn スレッドが飢餓状態になる
                # (P2 最終レビュー指摘)。time.sleep(0) は OS に一度制御を
                # 返すだけで、追いつく速度への影響はほぼ無い。
                time.sleep(0)
        return self.STEP_SECONDS
```

`tests/unit/test_clock.py` の末尾に追記:

```python
def test_advance_yields_when_behind_schedule():
    import time as time_module
    import unittest.mock as mock

    from omsim.sim.clock import SimClock

    clock = SimClock(realtime=True)
    clock._wall_start = time_module.monotonic() - 10.0  # 大きく遅延させる
    with mock.patch("time.sleep") as fake_sleep:
        clock.advance()
    fake_sleep.assert_called_once_with(0)
```

- [ ] **Step 5: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_clock.py tests/unit/test_recorder.py tests/unit/test_omsim_cli.py -v"`
Expected: 全 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed（`pgrep -af 'omsim.apps'` で残骸プロセスが無いことを先に確認しておく）

- [ ] **Step 6: コミット**

```bash
git add tests/integration/test_multi_node.py omsim/sim/recorder.py omsim/apps/omsim_main.py omsim/web/app.py omsim/sim/clock.py tests/unit/test_omsim_cli.py tests/unit/test_clock.py tests/unit/test_recorder.py
git commit -m "fix: RESPONSE_TIMEOUT定数化・Recorderのロック・Web既定バインド・SimClockのbusy loopを解消する"
```

---

## Task 6: PDO 通信パラメータ（1400h-1403h / 1800h-1803h）を実装する

**Files:**
- Create: `omsim/driver/pdo.py`
- Modify: `omsim/driver/model.py`
- Test: `tests/unit/test_pdo.py`（新規）
- Test: `tests/unit/test_driver_pdo_comm.py`（新規）

**Interfaces:**
- Consumes: なし（driver 層のみ）
- Produces:
  - `omsim/driver/pdo.py`:
    - `PDO_VALID_BIT = 1 << 31` / `PDO_RTR_BIT = 1 << 30` / `COB_ID_MASK = 0x7FF`
    - `RPDO_BASE_COB_ID = (0x200, 0x300, 0x400, 0x500)` / `TPDO_BASE_COB_ID = (0x180, 0x280, 0x380, 0x480)`
    - `RPDO_TRANSMISSION_TYPES = frozenset([0x00, 0xFE, 0xFF])`
    - `is_reserved_tpdo_transmission_type(value) -> bool`（`0xF1`-`0xFB`）
    - `is_supported_tpdo_transmission_type(value) -> bool`
    - `class PdoCommParams`: `.cob_id` / `.valid` / `.rtr_allowed` / `.transmission_type` / `.inhibit_time_100us` / `.event_timer_ms`、`.encode_cob_id_sub1() -> int`、`.decode_cob_id_sub1(raw) -> dict`（classmethod）
  - `DriverModel.rpdo_comm: List[PdoCommParams]`（長さ4）/ `DriverModel.tpdo_comm: List[PdoCommParams]`（長さ4）
  - 新規 SDO オブジェクト: `1400h`-`1403h`（sub0/sub1/sub2）、`1800h`-`1803h`（sub0/sub1/sub2/sub3/sub5）

### なぜこれをやるか

RPDO/TPDO のマッピング先を決めるには、まず「どの COB-ID で、有効かどうか、RTR を許すか、どの transmission type か」を SDO で読み書きできる必要がある。マッピング本体（`1600h`/`1A00h` 系、entry 一覧）は Task 7 で分離する（1 タスクの範囲を絞るため）。

**マッピングをバイト境界のみサポートする根拠**: EDS の既定マッピング（`1600h`-`1603h`/`1A00h`-`1A03h`）を確認すると、マッピングされるオブジェクトは全て 8/16/32 bit で、いずれもバイト境界に揃っている（`6040h`=16bit、`6060h`/`6061h`=8bit、`607Ah`/`60FFh`/`6064h`/`606Ch`=32bit）。ビット単位のサブバイトパッキング（例: 4bit を 2 つ 1 バイトに詰める）を使うマッピングは EDS 上どこにも存在しない。そのためこのフェーズはバイト境界のみをサポート対象とし、範囲外のマッピングを書こうとした場合は明示的に拒否する（Task 7 で実装）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_pdo.py`:

```python
from omsim.driver.pdo import (
    COB_ID_MASK,
    PDO_RTR_BIT,
    PDO_VALID_BIT,
    PdoCommParams,
    is_reserved_tpdo_transmission_type,
    is_supported_tpdo_transmission_type,
)


def test_valid_pdo_encodes_bit31_clear():
    params = PdoCommParams(cob_id=0x201, valid=True, rtr_allowed=True)
    assert params.encode_cob_id_sub1() & PDO_VALID_BIT == 0


def test_invalid_pdo_encodes_bit31_set():
    params = PdoCommParams(cob_id=0x201, valid=False, rtr_allowed=True)
    assert params.encode_cob_id_sub1() & PDO_VALID_BIT == PDO_VALID_BIT


def test_rtr_not_allowed_encodes_bit30_set():
    params = PdoCommParams(cob_id=0x181, valid=True, rtr_allowed=False)
    assert params.encode_cob_id_sub1() & PDO_RTR_BIT == PDO_RTR_BIT


def test_rtr_allowed_encodes_bit30_clear():
    params = PdoCommParams(cob_id=0x181, valid=True, rtr_allowed=True)
    assert params.encode_cob_id_sub1() & PDO_RTR_BIT == 0


def test_cob_id_round_trips_through_encode_decode():
    params = PdoCommParams(cob_id=0x301, valid=True, rtr_allowed=False)
    raw = params.encode_cob_id_sub1()
    decoded = PdoCommParams.decode_cob_id_sub1(raw)
    assert decoded == {"cob_id": 0x301, "rtr_allowed": True, "valid": True}


def test_cob_id_mask_is_11_bits():
    assert COB_ID_MASK == 0x7FF


def test_reserved_tpdo_transmission_types():
    for value in (0xF1, 0xF5, 0xFB):
        assert is_reserved_tpdo_transmission_type(value) is True
    for value in (0x00, 0xF0, 0xFC, 0xFF):
        assert is_reserved_tpdo_transmission_type(value) is False


def test_supported_tpdo_transmission_types():
    for value in (0x00, 0x01, 0xF0, 0xFC, 0xFD, 0xFE, 0xFF):
        assert is_supported_tpdo_transmission_type(value) is True
    for value in (0xF1, 0xFB):
        assert is_supported_tpdo_transmission_type(value) is False
```

`tests/unit/test_driver_pdo_comm.py`:

```python
import pytest

from omsim.driver.errors import ABORT_VALUE_RANGE, ObjectAccessError
from omsim.driver.model import DriverModel
from omsim.driver.pdo import PDO_RTR_BIT, PDO_VALID_BIT


def test_default_rpdo_cob_ids_follow_node_id():
    model = DriverModel(node_id=5)
    assert [c.cob_id for c in model.rpdo_comm] == [0x205, 0x305, 0x405, 0x505]
    assert all(c.valid for c in model.rpdo_comm)


def test_default_tpdo_cob_ids_follow_node_id_and_forbid_rtr():
    model = DriverModel(node_id=5)
    assert [c.cob_id for c in model.tpdo_comm] == [0x185, 0x285, 0x385, 0x485]
    assert all(c.valid and not c.rtr_allowed for c in model.tpdo_comm)


def test_default_transmission_types_match_eds():
    model = DriverModel(node_id=1)
    assert [c.transmission_type for c in model.rpdo_comm] == [255, 255, 255, 255]
    # 1800h/1801h は 255、1802h/1803h は 1 (EDS 実測値)
    assert [c.transmission_type for c in model.tpdo_comm] == [255, 255, 1, 1]


def test_default_inhibit_time_matches_eds():
    model = DriverModel(node_id=1)
    assert all(c.inhibit_time_100us == 50 for c in model.tpdo_comm)


def test_read_rpdo1_cob_id_sub1():
    model = DriverModel(node_id=3)
    assert model.read_object(0x1400, 1) == 0x203  # bit31/30 とも 0


def test_read_tpdo1_cob_id_sub1_has_rtr_bit_set():
    model = DriverModel(node_id=3)
    assert model.read_object(0x1800, 1) == (0x183 | PDO_RTR_BIT)


def test_write_transmission_type_updates_params():
    model = DriverModel(node_id=1)
    model.write_object(0x1800, 2, 5)
    assert model.tpdo_comm[0].transmission_type == 5


def test_write_reserved_tpdo_transmission_type_is_rejected():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x1800, 2, 0xF5)
    assert exc.value.abort_code == 0x06090030


def test_write_unsupported_rpdo_transmission_type_is_rejected():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x1400, 2, 0x01)  # RPDO は 0x00/0xFE/0xFF のみ
    assert exc.value.abort_code == 0x06090030


def test_write_inhibit_time():
    model = DriverModel(node_id=1)
    model.write_object(0x1800, 3, 100)
    assert model.tpdo_comm[0].inhibit_time_100us == 100


def test_write_event_timer():
    model = DriverModel(node_id=1)
    model.write_object(0x1800, 5, 200)
    assert model.tpdo_comm[0].event_timer_ms == 200


def test_disabling_then_enabling_a_pdo_round_trips():
    model = DriverModel(node_id=1)
    disabled = model.rpdo_comm[0].cob_id | PDO_VALID_BIT
    model.write_object(0x1400, 1, disabled)
    assert model.rpdo_comm[0].valid is False
    model.write_object(0x1400, 1, model.rpdo_comm[0].cob_id)  # 再度有効化
    assert model.rpdo_comm[0].valid is True


def test_all_four_rpdo_and_tpdo_slots_are_registered():
    model = DriverModel(node_id=1)
    for index in (0x1400, 0x1401, 0x1402, 0x1403):
        assert model.read_object(index, 0) == 2
    for index in (0x1800, 0x1801, 0x1802, 0x1803):
        assert model.read_object(index, 0) == 5
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_pdo.py tests/unit/test_driver_pdo_comm.py -q 2>&1 | tail -20"`
Expected: FAIL（`omsim.driver.pdo` が無い、`rpdo_comm` が無い）

- [ ] **Step 3: `omsim/driver/pdo.py` を書く**

```python
"""PDO 通信パラメータ・マッピングパラメータのビット表現。

CiA301 のビットフィールド (1400h-1403h/1800h-1803h の COB-ID sub1、
1600h-1603h/1A00h-1A03h のマッピングエントリ) を素の Python 値として
表現する。can/canopen を import しないこと (driver 層)。

参照: HP-5143E 4.7 (PDO, p31-33)、Object Dictionary 1400h/1800h 節
(実測値は本計画の「仕様で確認済みの事実」を参照)。
"""
import collections

PDO_VALID_BIT = 1 << 31
PDO_RTR_BIT = 1 << 30
COB_ID_MASK = 0x7FF

# RPDO/TPDO 既定 COB-ID のベース (node_id 加算前)。
RPDO_BASE_COB_ID = (0x200, 0x300, 0x400, 0x500)
TPDO_BASE_COB_ID = (0x180, 0x280, 0x380, 0x480)

RPDO_TRANSMISSION_TYPES = frozenset([0x00, 0xFE, 0xFF])


def is_reserved_tpdo_transmission_type(value):
    return 0xF1 <= value <= 0xFB


def is_supported_tpdo_transmission_type(value):
    if is_reserved_tpdo_transmission_type(value):
        return False
    return 0x00 <= value <= 0xFF


MappingEntry = collections.namedtuple("MappingEntry", ["index", "sub", "length_bits"])


def pack_mapping_entry(index, sub, length_bits):
    return ((index & 0xFFFF) << 16) | ((sub & 0xFF) << 8) | (length_bits & 0xFF)


def unpack_mapping_entry(raw):
    return MappingEntry(
        index=(raw >> 16) & 0xFFFF,
        sub=(raw >> 8) & 0xFF,
        length_bits=raw & 0xFF,
    )


class PdoCommParams(object):
    """1400h-1403h (RPDO) / 1800h-1803h (TPDO) 通信パラメータ 1 本ぶん。"""

    def __init__(self, cob_id, valid=True, rtr_allowed=True, transmission_type=255,
                 inhibit_time_100us=0, event_timer_ms=0):
        self.cob_id = cob_id
        self.valid = valid
        self.rtr_allowed = rtr_allowed
        self.transmission_type = transmission_type
        self.inhibit_time_100us = inhibit_time_100us
        self.event_timer_ms = event_timer_ms

    def encode_cob_id_sub1(self):
        value = self.cob_id & COB_ID_MASK
        if not self.rtr_allowed:
            value |= PDO_RTR_BIT
        if not self.valid:
            value |= PDO_VALID_BIT
        return value

    @classmethod
    def decode_cob_id_sub1(cls, raw):
        return {
            "cob_id": raw & COB_ID_MASK,
            "rtr_allowed": not bool(raw & PDO_RTR_BIT),
            "valid": not bool(raw & PDO_VALID_BIT),
        }


class PdoMappingParams(object):
    """1600h-1603h (RPDO) / 1A00h-1A03h (TPDO) マッピングパラメータ 1 本ぶん。"""

    MAX_ENTRIES = 4

    def __init__(self, entries=None):
        self.entries = list(entries) if entries else []

    @property
    def count(self):
        return len(self.entries)

    def total_bits(self):
        return sum(entry.length_bits for entry in self.entries)
```

- [ ] **Step 4: `DriverModel` に PDO 通信パラメータを追加する**

`omsim/driver/model.py` の import に追加:

```python
from omsim.driver.pdo import (
    RPDO_BASE_COB_ID,
    RPDO_TRANSMISSION_TYPES,
    TPDO_BASE_COB_ID,
    PdoCommParams,
    is_supported_tpdo_transmission_type,
)
```

`__init__` に追加（EDS 実測値どおりの既定値。TPDO3/4 の transmission type だけ EDS 上 1 であることに注意）:

```python
        self.rpdo_comm = [
            PdoCommParams(cob_id=RPDO_BASE_COB_ID[i] + node_id, valid=True,
                          rtr_allowed=True, transmission_type=255)
            for i in range(4)
        ]
        self.tpdo_comm = [
            PdoCommParams(cob_id=TPDO_BASE_COB_ID[i] + node_id, valid=True,
                          rtr_allowed=False,
                          transmission_type=(255 if i < 2 else 1),
                          inhibit_time_100us=50, event_timer_ms=0)
            for i in range(4)
        ]
```

`_SHADOW_DEEP_ATTRS`（Task 4 で作成）に追記:

```python
    _SHADOW_DEEP_ATTRS = (
        "state_machine", "plant", "alarms", "passthrough_values",
        "rpdo_comm", "rpdo_mapping", "tpdo_comm", "tpdo_mapping",
    )
```

（`rpdo_mapping`/`tpdo_mapping` は Task 7 で追加するため、この Task の時点では `AttributeError` になる。**Task 6 のこのコミットでは `_SHADOW_DEEP_ATTRS` を `"rpdo_comm", "tpdo_comm"` までに留め、Task 7 で `"rpdo_mapping", "tpdo_mapping"` を追記する。**）

PDO 通信パラメータの reader/writer をクラス本体に追加する（ループで 4 スロットぶんまとめて登録し、コード重複を避ける）:

```python
    # --- PDO 通信パラメータ (1400h-1403h / 1800h-1803h) ---

    def _read_pdo_comm_highest_sub(self, sub, count):
        return count

    def _read_pdo_comm_cob_id(self, params_list, slot):
        return params_list[slot].encode_cob_id_sub1()

    def _write_pdo_comm_cob_id(self, params_list, slot, value, allow_rtr_bit):
        raw = int(value) & 0xFFFFFFFF
        decoded = PdoCommParams.decode_cob_id_sub1(raw)
        if not allow_rtr_bit and not decoded["rtr_allowed"]:
            # RPDO の COB-ID には RTR ビットの意味が無い (常に ZERO 領域)。
            # 立てて書かれても無視して常に許可扱いにする (実害が無いため
            # abort まではしない)。
            decoded["rtr_allowed"] = True
        params_list[slot].cob_id = decoded["cob_id"]
        params_list[slot].rtr_allowed = decoded["rtr_allowed"]
        params_list[slot].valid = decoded["valid"]

    def _write_transmission_type(self, params_list, slot, value, allowed_check):
        value = int(value)
        if not allowed_check(value):
            raise ObjectAccessError(
                0x06090030, "{:02X}h は未対応の transmission type です".format(value))
        params_list[slot].transmission_type = value
```

各 RPDO/TPDO スロットの登録をループで行う（`DriverModel` クラス本体の末尾、`_PASSTHROUGH_PARAMETERS` 登録の直前に挿入）:

```python
    # RPDO 通信パラメータ (1400h-1403h)
    for _slot, _index in enumerate((0x1400, 0x1401, 0x1402, 0x1403)):
        def _make_rpdo_comm_handlers(slot=_slot, index=_index):
            def read_highest(self, sub):
                return 2

            def read_cob_id(self, sub):
                return self.rpdo_comm[slot].encode_cob_id_sub1()

            def write_cob_id(self, sub, value):
                self._write_pdo_comm_cob_id(self.rpdo_comm, slot, value, allow_rtr_bit=False)

            def read_tt(self, sub):
                return self.rpdo_comm[slot].transmission_type

            def write_tt(self, sub, value):
                self._write_transmission_type(
                    self.rpdo_comm, slot, value,
                    lambda v: v in RPDO_TRANSMISSION_TYPES)

            return read_highest, read_cob_id, write_cob_id, read_tt, write_tt

        _read_highest, _read_cob_id, _write_cob_id, _read_tt, _write_tt = (
            _make_rpdo_comm_handlers())
        router.reader(_index, 0)(_read_highest)
        router.reader(_index, 1)(_read_cob_id)
        router.writer(_index, 1)(_write_cob_id)
        router.reader(_index, 2)(_read_tt)
        router.writer(_index, 2)(_write_tt)
    del _slot, _index

    # TPDO 通信パラメータ (1800h-1803h)
    for _slot, _index in enumerate((0x1800, 0x1801, 0x1802, 0x1803)):
        def _make_tpdo_comm_handlers(slot=_slot, index=_index):
            def read_highest(self, sub):
                return 5

            def read_cob_id(self, sub):
                return self.tpdo_comm[slot].encode_cob_id_sub1()

            def write_cob_id(self, sub, value):
                self._write_pdo_comm_cob_id(self.tpdo_comm, slot, value, allow_rtr_bit=True)

            def read_tt(self, sub):
                return self.tpdo_comm[slot].transmission_type

            def write_tt(self, sub, value):
                self._write_transmission_type(
                    self.tpdo_comm, slot, value, is_supported_tpdo_transmission_type)

            def read_inhibit(self, sub):
                return self.tpdo_comm[slot].inhibit_time_100us

            def write_inhibit(self, sub, value):
                self.tpdo_comm[slot].inhibit_time_100us = int(value) & 0xFFFF

            def read_event(self, sub):
                return self.tpdo_comm[slot].event_timer_ms

            def write_event(self, sub, value):
                self.tpdo_comm[slot].event_timer_ms = int(value) & 0xFFFF

            return (read_highest, read_cob_id, write_cob_id, read_tt, write_tt,
                    read_inhibit, write_inhibit, read_event, write_event)

        (_read_highest, _read_cob_id, _write_cob_id, _read_tt, _write_tt,
         _read_inhibit, _write_inhibit, _read_event, _write_event) = (
            _make_tpdo_comm_handlers())
        router.reader(_index, 0)(_read_highest)
        router.reader(_index, 1)(_read_cob_id)
        router.writer(_index, 1)(_write_cob_id)
        router.reader(_index, 2)(_read_tt)
        router.writer(_index, 2)(_write_tt)
        router.reader(_index, 3)(_read_inhibit)
        router.writer(_index, 3)(_write_inhibit)
        router.reader(_index, 5)(_read_event)
        router.writer(_index, 5)(_write_event)
    del _slot, _index
```

**注意（クロージャの変数捕捉）**: `_make_rpdo_comm_handlers`/`_make_tpdo_comm_handlers` はキーワード引数の既定値 (`slot=_slot`) でループ変数を捕捉している。既定値を使わず自由変数のまま参照すると、`del` 後に呼ばれた際に全スロットが最後の値を参照してしまう既知の Python の罠のため、必ずこの形を守ること。

- [ ] **Step 5: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_pdo.py tests/unit/test_driver_pdo_comm.py -v"`
Expected: 全 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed

- [ ] **Step 6: コミット**

```bash
git add omsim/driver/pdo.py omsim/driver/model.py tests/unit/test_pdo.py tests/unit/test_driver_pdo_comm.py
git commit -m "feat: PDO 通信パラメータ (1400h-1403h/1800h-1803h) を実装する"
```

---

## Task 7: PDO マッピングパラメータ（1600h-1603h / 1A00h-1A03h）を実装する

**Files:**
- Modify: `omsim/driver/model.py`
- Test: `tests/unit/test_driver_pdo_mapping.py`（新規）

**Interfaces:**
- Consumes: Task 6 の `PdoMappingParams` / `PdoCommParams`
- Produces:
  - `DriverModel.rpdo_mapping: List[PdoMappingParams]`（長さ4）/ `DriverModel.tpdo_mapping: List[PdoMappingParams]`（長さ4）
  - 新規 SDO オブジェクト: `1600h`-`1603h`（sub0-4）、`1A00h`-`1A03h`（sub0-4）

### なぜこれをやるか

Task 6 で「どの COB-ID か」は決まったが、「その PDO に何が乗るか」はまだ決まっていない。ここでマッピングエントリの動的な読み書きを実装する。仕様（4.7.1）どおり、**マッピングは対応する PDO が bit31=1（無効）の間だけ変更できる**。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_driver_pdo_mapping.py`:

```python
import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import DriverModel
from omsim.driver.pdo import pack_mapping_entry


def test_default_rpdo1_mapping_is_controlword_only():
    model = DriverModel(node_id=1)
    assert model.rpdo_mapping[0].count == 1
    assert model.rpdo_mapping[0].entries[0].index == 0x6040
    assert model.rpdo_mapping[0].entries[0].length_bits == 16


def test_default_rpdo3_mapping_matches_eds():
    model = DriverModel(node_id=1)
    entries = model.rpdo_mapping[2].entries
    assert entries[0].index == 0x6040 and entries[0].length_bits == 16
    assert entries[1].index == 0x607A and entries[1].length_bits == 32


def test_default_tpdo1_mapping_is_statusword_only():
    model = DriverModel(node_id=1)
    assert model.tpdo_mapping[0].count == 1
    assert model.tpdo_mapping[0].entries[0].index == 0x6041


def test_read_mapping_sub0_returns_count():
    model = DriverModel(node_id=1)
    assert model.read_object(0x1601, 0) == 2


def test_read_mapping_entry_returns_packed_value():
    model = DriverModel(node_id=1)
    assert model.read_object(0x1600, 1) == pack_mapping_entry(0x6040, 0, 16)


def test_cannot_change_mapping_entry_while_pdo_is_enabled():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x1600, 1, pack_mapping_entry(0x6060, 0, 8))
    assert exc.value.abort_code == 0x08000022  # ABORT_DEVICE_STATE


def test_can_change_mapping_entry_after_disabling_the_pdo():
    model = DriverModel(node_id=1)
    disabled_cob_id = model.rpdo_comm[0].cob_id | (1 << 31)
    model.write_object(0x1400, 1, disabled_cob_id)
    model.write_object(0x1600, 0, 0)  # マッピングを一旦無効化 (4.7.1 手順②)
    model.write_object(0x1600, 1, pack_mapping_entry(0x6060, 0, 8))
    model.write_object(0x1600, 0, 1)  # 有効化 (手順④)
    assert model.rpdo_mapping[0].entries[0].index == 0x6060


def test_mapping_sub0_cannot_exceed_four():
    model = DriverModel(node_id=1)
    model.write_object(0x1400, 1, model.rpdo_comm[0].cob_id | (1 << 31))
    model.write_object(0x1600, 0, 0)
    with pytest.raises(ObjectAccessError):
        model.write_object(0x1600, 0, 5)


def test_non_byte_aligned_length_is_rejected():
    """このフェーズはバイト境界マッピングのみ対応 (EDS の既定マッピングが
    全てバイト境界であるため)。ビット単位のパッキングは明示的に拒否する。"""
    model = DriverModel(node_id=1)
    model.write_object(0x1400, 1, model.rpdo_comm[0].cob_id | (1 << 31))
    model.write_object(0x1600, 0, 0)
    with pytest.raises(ObjectAccessError):
        model.write_object(0x1600, 1, pack_mapping_entry(0x6040, 0, 12))
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_driver_pdo_mapping.py -q 2>&1 | tail -20"`
Expected: FAIL（`rpdo_mapping` が無い）

- [ ] **Step 3: `DriverModel` にマッピングパラメータを追加する**

`omsim/driver/model.py` の import に追加:

```python
from omsim.driver.pdo import MappingEntry, PdoMappingParams, pack_mapping_entry, unpack_mapping_entry
```

`__init__` に追加（EDS 実測どおりの既定マッピング）:

```python
        self.rpdo_mapping = [
            PdoMappingParams([MappingEntry(0x6040, 0, 16)]),
            PdoMappingParams([MappingEntry(0x6040, 0, 16), MappingEntry(0x6060, 0, 8)]),
            PdoMappingParams([MappingEntry(0x6040, 0, 16), MappingEntry(0x607A, 0, 32)]),
            PdoMappingParams([MappingEntry(0x6040, 0, 16), MappingEntry(0x60FF, 0, 32)]),
        ]
        self.tpdo_mapping = [
            PdoMappingParams([MappingEntry(0x6041, 0, 16)]),
            PdoMappingParams([MappingEntry(0x6041, 0, 16), MappingEntry(0x6061, 0, 8)]),
            PdoMappingParams([MappingEntry(0x6041, 0, 16), MappingEntry(0x6064, 0, 32)]),
            PdoMappingParams([MappingEntry(0x6041, 0, 16), MappingEntry(0x606C, 0, 32)]),
        ]
```

`_SHADOW_DEEP_ATTRS` に追記（Task 6 で保留していた `rpdo_mapping`/`tpdo_mapping` を追加する）:

```python
    _SHADOW_DEEP_ATTRS = (
        "state_machine", "plant", "alarms", "passthrough_values",
        "rpdo_comm", "rpdo_mapping", "tpdo_comm", "tpdo_mapping",
    )
```

マッピング用の共通ヘルパーをクラス本体に追加:

```python
    def _mapping_disabled_guard(self, comm_params):
        if comm_params.valid:
            raise ObjectAccessError(
                ABORT_DEVICE_STATE,
                "対応する PDO が有効 (bit31=0) な間はマッピングを変更できません")

    def _write_mapping_count(self, mapping_params, comm_params, value):
        self._mapping_disabled_guard(comm_params)
        count = int(value)
        if not (0 <= count <= PdoMappingParams.MAX_ENTRIES):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "マッピング数は 0-4")
        if count == 0:
            mapping_params.entries = []
            return
        if count > len(mapping_params.entries):
            raise ObjectAccessError(
                ABORT_DEVICE_STATE,
                "sub{} まで書き込んでから sub0 を {} にしてください".format(count, count))
        mapping_params.entries = mapping_params.entries[:count]

    def _write_mapping_entry(self, mapping_params, comm_params, sub, value):
        self._mapping_disabled_guard(comm_params)
        entry = unpack_mapping_entry(int(value) & 0xFFFFFFFF)
        if entry.length_bits % 8 != 0:
            raise ObjectAccessError(
                ABORT_VALUE_RANGE,
                "{}bit はバイト境界に揃っていません (このフェーズはバイト単位のみ対応)"
                .format(entry.length_bits))
        while len(mapping_params.entries) < sub:
            mapping_params.entries.append(MappingEntry(0, 0, 0))
        mapping_params.entries[sub - 1] = entry
```

各 RPDO/TPDO マッピングスロットの登録をループで行う（Task 6 の PDO 通信パラメータ登録の直後に挿入）:

```python
    # RPDO マッピングパラメータ (1600h-1603h)
    for _slot, _index in enumerate((0x1600, 0x1601, 0x1602, 0x1603)):
        def _make_rpdo_mapping_handlers(slot=_slot):
            def read_count(self, sub):
                return self.rpdo_mapping[slot].count

            def write_count(self, sub, value):
                self._write_mapping_count(self.rpdo_mapping[slot], self.rpdo_comm[slot], value)

            def read_entry(self, sub):
                entries = self.rpdo_mapping[slot].entries
                if sub > len(entries):
                    return 0
                e = entries[sub - 1]
                return pack_mapping_entry(e.index, e.sub, e.length_bits)

            def write_entry(self, sub, value):
                self._write_mapping_entry(self.rpdo_mapping[slot], self.rpdo_comm[slot], sub, value)

            return read_count, write_count, read_entry, write_entry

        _read_count, _write_count, _read_entry, _write_entry = _make_rpdo_mapping_handlers()
        router.reader(_index, 0)(_read_count)
        router.writer(_index, 0)(_write_count)
        for _sub in (1, 2, 3, 4):
            router.reader(_index, _sub)(_read_entry)
            router.writer(_index, _sub)(_write_entry)
    del _slot, _index, _sub

    # TPDO マッピングパラメータ (1A00h-1A03h)
    for _slot, _index in enumerate((0x1A00, 0x1A01, 0x1A02, 0x1A03)):
        def _make_tpdo_mapping_handlers(slot=_slot):
            def read_count(self, sub):
                return self.tpdo_mapping[slot].count

            def write_count(self, sub, value):
                self._write_mapping_count(self.tpdo_mapping[slot], self.tpdo_comm[slot], value)

            def read_entry(self, sub):
                entries = self.tpdo_mapping[slot].entries
                if sub > len(entries):
                    return 0
                e = entries[sub - 1]
                return pack_mapping_entry(e.index, e.sub, e.length_bits)

            def write_entry(self, sub, value):
                self._write_mapping_entry(self.tpdo_mapping[slot], self.tpdo_comm[slot], sub, value)

            return read_count, write_count, read_entry, write_entry

        _read_count, _write_count, _read_entry, _write_entry = _make_tpdo_mapping_handlers()
        router.reader(_index, 0)(_read_count)
        router.writer(_index, 0)(_write_count)
        for _sub in (1, 2, 3, 4):
            router.reader(_index, _sub)(_read_entry)
            router.writer(_index, _sub)(_write_entry)
    del _slot, _index, _sub
```

- [ ] **Step 4: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_driver_pdo_mapping.py -v"`
Expected: 全 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed（`omsim --coverage` の実装済み件数が増えていることも実測して報告書に記録する）

- [ ] **Step 5: コミット**

```bash
git add omsim/driver/model.py tests/unit/test_driver_pdo_mapping.py
git commit -m "feat: PDO マッピングパラメータ (1600h-1603h/1A00h-1A03h) の動的変更を実装する"
```

---

## Task 8: RPDO 受信を実装する

**Files:**
- Create: `omsim/node/realtime_bridge.py`
- Modify: `omsim/sim/manager.py`
- Test: `tests/unit/test_realtime_bridge.py`（新規）
- Test: `tests/integration/test_pdo_over_vcan.py`（新規）

**Interfaces:**
- Consumes: `DriverModel.rpdo_comm` / `.rpdo_mapping`、`CommandQueue.put(index, sub, value, trigger)`
- Produces:
  - `omsim/node/realtime_bridge.py`:
    - `class RealtimeBridge`: `.attach(node, model, od, queue, sync_counter)` / `.step(node_id, model, network, sim_time)` / `.on_sync(node_id, model, network, sim_time)`（`.step`/`.on_sync` は Task 9 で TPDO 送信を追加するまでは RPDO 分の内部状態更新のみ）
  - `NodeManager` が `self.eds[node_id]`（`od`）を保持し、`self.bridge = RealtimeBridge()` を持つ

### なぜこれをやるか

Task 6/7 で PDO のパラメータは読み書きできるようになったが、実際に CAN フレームを受信してキューへ積む配線がまだ無い。`canopen.LocalNode` の `pdo`/`rpdo`/`tpdo`（`canopen.pdo` サブモジュール）は SDO クライアント経由で自分自身の設定を読み書きする設計（`RemoteNode` を主眼にした実装）で、ローカルに信頼できるこのノードの使い方とは噛み合わないため使わない。代わりに `Recorder.FrameListener` と同じパターンで `can.Listener` を自前で実装する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_realtime_bridge.py`（`can.Message` を直接組み立てて `on_message_received` を呼ぶユニットテスト。CAN バスは使わない）:

```python
import can

from omsim.driver.model import DriverModel
from omsim.node.eds import DEFAULT_EDS_PATH, load_eds
from omsim.node.realtime_bridge import RealtimeBridge
from omsim.sim.command_queue import CommandQueue
from omsim.sim.sync_counter import SyncCounter


def make_listener(node_id=1):
    od = load_eds(DEFAULT_EDS_PATH)
    model = DriverModel(node_id=node_id)
    queue = CommandQueue()
    sync_counter = SyncCounter()
    bridge = RealtimeBridge()
    listener = bridge._make_listener(model, od, queue, sync_counter, node_id)
    return listener, model, queue, sync_counter


def test_rpdo1_frame_queues_controlword_as_immediate():
    listener, model, queue, _sync = make_listener()
    msg = can.Message(arbitration_id=0x201, data=[0x07, 0x00], is_extended_id=False)
    listener.on_message_received(msg)
    assert queue.pending_count() == 1
    queue.drain(model)
    assert model.read_object(0x6040) == 0x0007


def test_rpdo2_frame_decodes_two_mapped_objects():
    listener, model, queue, _sync = make_listener()
    # RPDO2 既定マッピング: 6040h(16bit) + 6060h(8bit)
    msg = can.Message(arbitration_id=0x301, data=[0x0F, 0x00, 0x03], is_extended_id=False)
    listener.on_message_received(msg)
    queue.drain(model)
    assert model.read_object(0x6040) == 0x000F


def test_sync_transmission_type_rpdo_is_queued_as_sync_trigger():
    listener, model, queue, _sync = make_listener()
    model.write_object(0x1400, 2, 0x00)  # SYNC 反映へ変更
    msg = can.Message(arbitration_id=0x201, data=[0x07, 0x00], is_extended_id=False)
    listener.on_message_received(msg)
    queue.drain(model, sync_received=False)
    assert model.read_object(0x6040) == 0x0004  # まだ既定値のまま (SYNC 待ち)
    queue.drain(model, sync_received=True)
    assert model.read_object(0x6040) == 0x0007


def test_disabled_rpdo_is_ignored():
    listener, model, queue, _sync = make_listener()
    model.write_object(0x1400, 1, model.rpdo_comm[0].cob_id | (1 << 31))  # 無効化
    msg = can.Message(arbitration_id=0x201, data=[0x07, 0x00], is_extended_id=False)
    listener.on_message_received(msg)
    assert queue.pending_count() == 0


def test_unrelated_cob_id_is_ignored():
    listener, model, queue, _sync = make_listener()
    msg = can.Message(arbitration_id=0x999, data=[0x07, 0x00], is_extended_id=False)
    listener.on_message_received(msg)
    assert queue.pending_count() == 0


def test_sync_frame_notifies_sync_counter():
    listener, _model, _queue, sync_counter = make_listener()
    msg = can.Message(arbitration_id=0x80, data=[], is_extended_id=False)
    listener.on_message_received(msg)
    assert sync_counter.take() == 1


def test_remote_frame_at_sync_cob_id_is_not_treated_as_sync():
    listener, _model, _queue, sync_counter = make_listener()
    msg = can.Message(arbitration_id=0x80, data=[], is_extended_id=False, is_remote_frame=True)
    listener.on_message_received(msg)
    assert sync_counter.take() == 0
```

`tests/integration/test_pdo_over_vcan.py`:

```python
import time

import pytest

pytestmark = pytest.mark.vcan


def test_rpdo1_over_vcan_moves_the_state_machine(stepped_sim, master):
    """マスタ役から RPDO1 (COB-ID 0x201) へ Controlword を送ると、
    キュー経由で次の step() に反映されることを実バス経由で確認する。"""
    node_id = 1
    cob_id = 0x200 + node_id
    master.send_message(cob_id, bytes([0x06, 0x00]))  # shutdown
    time.sleep(0.05)
    stepped_sim.step()
    assert stepped_sim.models[node_id].read_object(0x6040) == 0x0006
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_realtime_bridge.py -q 2>&1 | tail -20"`
Expected: FAIL（`omsim.node.realtime_bridge` が無い、`omsim.sim.sync_counter` が無い）

- [ ] **Step 3: `SyncCounter` を書く**

`omsim/sim/sync_counter.py`:

```python
"""CAN 受信スレッドから step() 側へ SYNC 受信を伝える。

step() は 1ms ごとに 1 回だけ呼ばれるため、1ms 未満の間隔で複数の
SYNC が届いた場合は 1 回として扱う (現実的な運用で SYNC 周期が 1ms を
下回ることは想定しないため、実害は無い)。
"""
import threading


class SyncCounter(object):
    def __init__(self):
        self._lock = threading.Lock()
        self._pending = 0

    def notify(self):
        with self._lock:
            self._pending += 1

    def take(self):
        """溜まった SYNC 受信回数を返し、0 にリセットする。"""
        with self._lock:
            pending, self._pending = self._pending, 0
        return pending
```

- [ ] **Step 4: `realtime_bridge.py` を書く（RPDO 受信 + SYNC 検出のみ）**

`omsim/node/realtime_bridge.py`:

```python
"""PDO (RPDO 受信 / TPDO 送信) と SYNC を CAN バスへ配線する。

canopen.LocalNode は SDO/NMT/EMCY のみ扱い、PDO/SYNC の送受信は自前で
行う。canopen.pdo サブモジュールは SDO クライアント経由で自分自身の
設定を読み書きする設計 (RemoteNode を主眼にした実装) で、プロセス内で
DriverModel と直結しているこのノードの使い方とは噛み合わないため使わない。

Recorder.FrameListener と同じパターンで can.Listener を直接実装する。
値のエンコード/デコードは自前でビット演算をせず、canopen の
ObjectDictionary が持つ ODVariable.encode_raw()/decode_raw() をそのまま
使う (符号付き整数の扱いを canopen 本体と一致させるため)。
"""
import can

from omsim.driver.pdo import unpack_mapping_entry  # noqa: F401 (将来のデバッグ用に残す)


def _od_variable(od, index, sub):
    obj = od[index]
    if hasattr(obj, "subindices"):
        return obj[sub]
    return obj


def _decode_rpdo(od, data, mapping):
    """マッピングに従って data を分解し [(index, sub, value), ...] を返す。

    バイト境界のみ対応 (Task 7 の書込みバリデーションで保証済み)。
    """
    decoded = []
    offset_bytes = 0
    for entry in mapping.entries:
        length_bytes = entry.length_bits // 8
        variable = _od_variable(od, entry.index, entry.sub)
        chunk = bytes(data[offset_bytes:offset_bytes + length_bytes])
        value = variable.decode_raw(chunk)
        decoded.append((entry.index, entry.sub, value))
        offset_bytes += length_bytes
    return decoded


class _NodeListener(can.Listener):
    """1 ノードぶんの RPDO / SYNC 受信を捌く。node guarding / Heartbeat
    consumer の受信は Task 11 でこのクラスに追加する。"""

    def __init__(self, model, od, queue, sync_counter):
        self._model = model
        self._od = od
        self._queue = queue
        self._sync_counter = sync_counter

    def on_message_received(self, msg):
        if getattr(msg, "is_error_frame", False):
            return
        can_id = msg.arbitration_id
        is_rtr = getattr(msg, "is_remote_frame", False)

        if not is_rtr and can_id == (self._model.sync_cob_id & 0x7FF):
            self._sync_counter.notify()
            return

        if not is_rtr:
            self._handle_rpdo(can_id, bytes(msg.data))

    def _handle_rpdo(self, can_id, data):
        for slot in range(4):
            comm = self._model.rpdo_comm[slot]
            if comm.valid and comm.cob_id == can_id:
                trigger = "sync" if comm.transmission_type == 0x00 else "immediate"
                mapping = self._model.rpdo_mapping[slot]
                for index, sub, value in _decode_rpdo(self._od, data, mapping):
                    self._queue.put(index, sub, value, trigger=trigger)
                return

    def on_error(self, exc):
        pass  # 個別フレームのエラーで受信スレッドを止めない (Recorder.FrameListener と同じ方針)


class RealtimeBridge(object):
    """NodeManager が全ノードぶん共有して使う。"""

    def __init__(self):
        self._listeners = {}

    def _make_listener(self, model, od, queue, sync_counter, node_id):
        return _NodeListener(model, od, queue, sync_counter)

    def attach(self, node, model, od, queue, sync_counter):
        """node が Network に登録済みの状態で呼ぶ。"""
        listener = self._make_listener(model, od, queue, sync_counter, model.node_id)
        self._listeners[model.node_id] = listener
        network = node.network
        network.listeners.append(listener)
        notifier = getattr(network, "notifier", None)
        if notifier is not None:
            notifier.add_listener(listener)
```

`DriverModel` に `sync_cob_id` 属性が必要（現時点では未定義）。`omsim/driver/model.py` の `__init__` に追加:

```python
        # 1005h COB-ID SYNC message。producer/consumer の詳細実装は Task 10。
        self.sync_cob_id = 0x80
        self.sync_producer_enabled = False
        self.sync_period_us = 0
```

- [ ] **Step 5: `NodeManager` に配線する**

`omsim/sim/manager.py` の変更:

```python
from omsim.node.realtime_bridge import RealtimeBridge
from omsim.sim.sync_counter import SyncCounter
```

`__init__`:

```python
        self.eds = {}
        self.sync_counters = {}
        self.bridge = RealtimeBridge()
        for spec in specs:
            od = load_eds(spec.eds)
            model = DriverModel(node_id=spec.node_id)
            queue = CommandQueue()
            self.models[spec.node_id] = model
            self.queues[spec.node_id] = queue
            self.eds[spec.node_id] = od
            self.sync_counters[spec.node_id] = SyncCounter()
            self.nodes[spec.node_id] = build_local_node(
                spec.node_id, od, model, queue=queue)
```

`start()` に追記（`boot_local_node(node)` の直後）:

```python
        for node in self.nodes.values():
            self.network[node.id] = node
            boot_local_node(node)
            self.bridge.attach(
                node, self.models[node.id], self.eds[node.id],
                self.queues[node.id], self.sync_counters[node.id])
```

`step()` を SYNC 受信を反映する形に変える:

```python
    def step(self):
        dt = self.clock.advance()
        for node_id, model in self.models.items():
            sync_received = self.sync_counters[node_id].take() > 0
            for item, err in self.queues[node_id].drain(model, sync_received=sync_received):
                logger.warning(
                    "node%d: %04Xh:%02X への書込み %s が拒否されました: %s",
                    node_id, item.index, item.sub, item.value, err,
                )
            model.step(dt)
            self._drain_emcy(node_id, model)
```

- [ ] **Step 6: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_realtime_bridge.py -v"`
Expected: 全 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && pgrep -af 'omsim.apps'; python3 -m pytest tests/integration/test_pdo_over_vcan.py -v"`
Expected: PASS（`pgrep` で残骸プロセスが無いことを先に確認する）

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed

- [ ] **Step 7: コミット**

```bash
git add omsim/node/realtime_bridge.py omsim/sim/sync_counter.py omsim/sim/manager.py omsim/driver/model.py tests/unit/test_realtime_bridge.py tests/integration/test_pdo_over_vcan.py
git commit -m "feat: RPDO 受信と SYNC フレーム検出を実装する"
```

---

## Task 9: TPDO 送信を実装する（transmission type エンジン）

**Files:**
- Modify: `omsim/node/realtime_bridge.py`
- Modify: `omsim/sim/manager.py`
- Test: `tests/unit/test_realtime_bridge.py`（追記）
- Test: `tests/integration/test_pdo_over_vcan.py`（追記）

**Interfaces:**
- Consumes: `DriverModel.tpdo_comm` / `.tpdo_mapping`、`RealtimeBridge`（Task 8）
- Produces:
  - `RealtimeBridge.on_sync(node_id, model, network, sim_time)` — 同期系 transmission type（`0x00`/`0x01`-`0xF0`/`0xFC`）を進める
  - `RealtimeBridge.step(node_id, model, network, sim_time)` — 非同期系（`0xFE`/`0xFF`）の inhibit time / event timer を判定する

### なぜこれをやるか

Task 6/7 で TPDO のパラメータは持てるようになったが、実際に送信するロジックがまだ無い。4.7.2 の transmission type ごとの送信規則をここで実装する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_realtime_bridge.py` の末尾に追記:

```python
class FakeNetwork(object):
    def __init__(self):
        self.sent = []

    def send_message(self, cob_id, data):
        self.sent.append((cob_id, bytes(data)))


def make_bridge_and_model(node_id=1):
    od = load_eds(DEFAULT_EDS_PATH)
    model = DriverModel(node_id=node_id)
    bridge = RealtimeBridge()
    return bridge, model, od


def test_tpdo1_sync_acyclic_sends_once_after_a_change():
    bridge, model, od = make_bridge_and_model()
    network = FakeNetwork()
    model.write_object(0x6040, 0, 0x0006)  # statusword を変化させる
    bridge.on_sync(1, model, network, od, sim_time=0.0)
    assert len(network.sent) == 1
    assert network.sent[0][0] == model.tpdo_comm[0].cob_id


def test_tpdo1_sync_acyclic_does_not_resend_without_a_change():
    bridge, model, od = make_bridge_and_model()
    network = FakeNetwork()
    bridge.on_sync(1, model, network, od, sim_time=0.0)
    first_count = len(network.sent)
    bridge.on_sync(1, model, network, od, sim_time=0.001)
    assert len(network.sent) == first_count  # 変化なしなので増えない


def test_tpdo3_cyclic_nth_sync_sends_every_n_syncs():
    bridge, model, od = make_bridge_and_model()
    network = FakeNetwork()
    model.write_object(0x1802, 2, 3)  # 3 回目の SYNC ごとに送信
    for _ in range(2):
        bridge.on_sync(1, model, network, od, sim_time=0.0)
    assert len(network.sent) == 0
    bridge.on_sync(1, model, network, od, sim_time=0.0)
    assert len(network.sent) == 1


def test_event_driven_tpdo_sends_after_inhibit_time_elapses():
    bridge, model, od = make_bridge_and_model()
    network = FakeNetwork()
    model.write_object(0x1800, 3, 10)  # inhibit = 10 * 100us = 1ms
    bridge.step(1, model, network, od, sim_time=0.0)  # 初回送信
    initial = len(network.sent)
    model.write_object(0x6040, 0, 0x0006)  # 変化させる
    bridge.step(1, model, network, od, sim_time=0.0005)  # inhibit 未経過
    assert len(network.sent) == initial
    bridge.step(1, model, network, od, sim_time=0.0011)  # inhibit 経過
    assert len(network.sent) == initial + 1


def test_event_timer_resends_even_without_a_change():
    bridge, model, od = make_bridge_and_model()
    network = FakeNetwork()
    model.write_object(0x1800, 5, 5)  # event timer = 5ms
    bridge.step(1, model, network, od, sim_time=0.0)
    initial = len(network.sent)
    bridge.step(1, model, network, od, sim_time=0.006)  # 変化無しでも 5ms 経過
    assert len(network.sent) == initial + 1


def test_disabled_tpdo_never_sends():
    bridge, model, od = make_bridge_and_model()
    network = FakeNetwork()
    model.write_object(0x1800, 1, model.tpdo_comm[0].cob_id | (1 << 31))
    bridge.on_sync(1, model, network, od, sim_time=0.0)
    bridge.step(1, model, network, od, sim_time=0.0)
    assert network.sent == []
```

`tests/integration/test_pdo_over_vcan.py` の末尾に追記:

```python
def test_tpdo1_over_vcan_reflects_statusword_after_change(stepped_sim, master):
    """TPDO1 (COB-ID 0x181) が Statusword の変化を実バス経由で送信することを確認する。"""
    import can

    node_id = 1
    bus = can.interface.Bus(channel="vcan0", interface="socketcan",
                             can_filters=[{"can_id": 0x180 + node_id, "can_mask": 0x7FF}])
    try:
        master.send_message(0x200 + node_id, bytes([0x06, 0x00]))  # RPDO1 で shutdown
        time.sleep(0.05)
        stepped_sim.step()  # queue drain + on_sync/step は step() 内で呼ばれる (Task 9 Step 3)
        master.send_message(0x80, bytes())  # SYNC
        time.sleep(0.05)
        msg = bus.recv(timeout=1.0)
        assert msg is not None
        assert msg.arbitration_id == 0x180 + node_id
    finally:
        bus.shutdown()
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_realtime_bridge.py -k Tpdo -q 2>&1 | tail -20"`
Expected: FAIL（`on_sync`/`step` が無い）

- [ ] **Step 3: `realtime_bridge.py` に TPDO 送信を実装する**

`omsim/node/realtime_bridge.py` に追加:

```python
def _encode_tpdo(od, model, mapping):
    chunks = []
    for entry in mapping.entries:
        variable = _od_variable(od, entry.index, entry.sub)
        value = model.read_object(entry.index, entry.sub)
        chunks.append(variable.encode_raw(value))
    return b"".join(chunks)


class _TpdoRuntime(object):
    """トランスポート側の送信管理状態。DriverModel には持たせない
    (デバイスの状態ではなく、送信タイミングの内部管理だけのため)。"""

    def __init__(self):
        self.last_bytes = None
        self.sync_count = 0
        self.pending_change = False
        self.last_transmit_time = None
```

`RealtimeBridge.__init__` を変更:

```python
    def __init__(self):
        self._listeners = {}
        self._tpdo_runtime = {}  # node_id -> [runtime_slot0..3]
```

`attach` に追記:

```python
        self._tpdo_runtime[model.node_id] = [_TpdoRuntime() for _ in range(4)]
```

`RealtimeBridge` に `on_sync`/`step`/`_send_tpdo` を追加:

```python
    def _send_tpdo(self, network, model, od, comm, mapping, runtime, sim_time):
        data = _encode_tpdo(od, model, mapping)
        network.send_message(comm.cob_id, data)
        runtime.last_bytes = data
        runtime.pending_change = False
        runtime.last_transmit_time = sim_time

    def on_sync(self, node_id, model, network, od, sim_time):
        """SYNC 受信のたびに呼ぶ: 同期系 TPDO (0x00/0x01-0xF0/0xFC) を進める。"""
        runtimes = self._tpdo_runtime[node_id]
        for slot, comm in enumerate(model.tpdo_comm):
            if not comm.valid:
                continue
            mapping = model.tpdo_mapping[slot]
            runtime = runtimes[slot]
            tt = comm.transmission_type
            if tt == 0x00:
                current = _encode_tpdo(od, model, mapping)
                if runtime.last_bytes is None or current != runtime.last_bytes:
                    runtime.pending_change = True
                if runtime.pending_change:
                    self._send_tpdo(network, model, od, comm, mapping, runtime, sim_time)
            elif 0x01 <= tt <= 0xF0:
                runtime.sync_count += 1
                if runtime.sync_count >= tt:
                    self._send_tpdo(network, model, od, comm, mapping, runtime, sim_time)
                    runtime.sync_count = 0
            elif tt == 0xFC:
                runtime.last_bytes = _encode_tpdo(od, model, mapping)  # サンプルのみ

    def step(self, node_id, model, network, od, sim_time):
        """1ms ごとに呼ぶ: 非同期系 TPDO (0xFE/0xFF) の inhibit/event timer を判定する。"""
        runtimes = self._tpdo_runtime[node_id]
        for slot, comm in enumerate(model.tpdo_comm):
            if not comm.valid or comm.transmission_type not in (0xFE, 0xFF):
                continue
            mapping = model.tpdo_mapping[slot]
            runtime = runtimes[slot]
            current = _encode_tpdo(od, model, mapping)
            if runtime.last_bytes is None or current != runtime.last_bytes:
                runtime.pending_change = True
            if runtime.last_transmit_time is None:
                self._send_tpdo(network, model, od, comm, mapping, runtime, sim_time)
                continue
            elapsed = sim_time - runtime.last_transmit_time
            inhibit_seconds = comm.inhibit_time_100us * 100e-6
            if runtime.pending_change and elapsed >= inhibit_seconds:
                self._send_tpdo(network, model, od, comm, mapping, runtime, sim_time)
                continue
            if comm.event_timer_ms and elapsed >= comm.event_timer_ms / 1000.0:
                self._send_tpdo(network, model, od, comm, mapping, runtime, sim_time)
```

- [ ] **Step 4: `NodeManager.step()` から呼ぶ**

`omsim/sim/manager.py::step()` を変更（`model.step(dt)` の後）:

```python
    def step(self):
        dt = self.clock.advance()
        for node_id, model in self.models.items():
            sync_received = self.sync_counters[node_id].take() > 0
            for item, err in self.queues[node_id].drain(model, sync_received=sync_received):
                logger.warning(
                    "node%d: %04Xh:%02X への書込み %s が拒否されました: %s",
                    node_id, item.index, item.sub, item.value, err,
                )
            model.step(dt)
            self._drain_emcy(node_id, model)
            if self.network is not None and self._started:
                od = self.eds[node_id]
                if sync_received:
                    self.bridge.on_sync(node_id, model, self.network, od, self.clock.now)
                self.bridge.step(node_id, model, self.network, od, self.clock.now)
```

（`network is None` の単体テストでは TPDO 送信をスキップする。`network` フィールドを直接 `send_message` するため、`self.network` を渡す。）

- [ ] **Step 5: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_realtime_bridge.py -v"`
Expected: 全 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && pgrep -af 'omsim.apps'; python3 -m pytest tests/integration/test_pdo_over_vcan.py -v"`
Expected: 全 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed

- [ ] **Step 6: コミット**

```bash
git add omsim/node/realtime_bridge.py omsim/sim/manager.py tests/unit/test_realtime_bridge.py tests/integration/test_pdo_over_vcan.py
git commit -m "feat: TPDO 送信 (transmission type エンジン: sync/cyclic/event-driven) を実装する"
```

---

## Task 10: SYNC producer/consumer（1005h/1006h）を実装する

**Files:**
- Modify: `omsim/driver/model.py`
- Modify: `omsim/node/realtime_bridge.py`
- Modify: `omsim/sim/manager.py`
- Test: `tests/unit/test_driver_sync.py`（新規）
- Test: `tests/integration/test_pdo_over_vcan.py`（追記）

**Interfaces:**
- Consumes: `DriverModel.sync_cob_id` / `.sync_producer_enabled` / `.sync_period_us`（Task 8 で導入済み）
- Produces:
  - 新規 SDO オブジェクト `1005h`（COB-ID SYNC message）/ `1006h`（Communication cycle period）
  - `RealtimeBridge.step()` が、producer 有効なノードについて周期的に SYNC フレームを送信する

### なぜこれをやるか

Task 8/9 は「SYNC を受信したら」の消費側だけを実装した。ここで `1005h`/`1006h` を SDO で読み書き可能にし、bit30 が立っている場合は omsim 自身が SYNC を生成できるようにする（4.4 実測: 「To enable Sync producer mode, bit 30 must be set in COB-ID SYNC message object (1005h)」）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_driver_sync.py`:

```python
import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import DriverModel


def test_default_sync_cob_id_is_0x80():
    model = DriverModel(node_id=1)
    assert model.read_object(0x1005) == 0x80
    assert model.sync_producer_enabled is False


def test_writing_bit30_enables_producer_mode():
    model = DriverModel(node_id=1)
    model.write_object(0x1005, 0, 0x80 | (1 << 30))
    assert model.sync_producer_enabled is True
    assert model.sync_cob_id == 0x80


def test_writing_cob_id_updates_sync_cob_id():
    model = DriverModel(node_id=1)
    model.write_object(0x1005, 0, 0x90)
    assert model.sync_cob_id == 0x90


def test_default_communication_cycle_period_is_zero():
    model = DriverModel(node_id=1)
    assert model.read_object(0x1006) == 0
    assert model.sync_period_us == 0


def test_writing_communication_cycle_period():
    model = DriverModel(node_id=1)
    model.write_object(0x1006, 0, 10000)
    assert model.sync_period_us == 10000


def test_communication_cycle_period_out_of_range_is_rejected():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError):
        model.write_object(0x1006, 0, 1000001)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_driver_sync.py -q 2>&1 | tail -20"`
Expected: FAIL（`1005h`/`1006h` が abort する）

- [ ] **Step 3: `DriverModel` に 1005h/1006h を実装する**

`omsim/driver/model.py` のクラス本体に追加:

```python
    _SYNC_PRODUCER_BIT = 1 << 30

    @router.reader(0x1005)
    def _read_sync_cob_id(self, sub):
        value = self.sync_cob_id & 0x7FF
        if self.sync_producer_enabled:
            value |= self._SYNC_PRODUCER_BIT
        return value

    @router.writer(0x1005)
    def _write_sync_cob_id(self, sub, value):
        raw = int(value) & 0xFFFFFFFF
        self.sync_cob_id = raw & 0x7FF
        self.sync_producer_enabled = bool(raw & self._SYNC_PRODUCER_BIT)

    @router.reader(0x1006)
    def _read_sync_period(self, sub):
        return self.sync_period_us

    @router.writer(0x1006)
    def _write_sync_period(self, sub, value):
        period = int(value)
        if not (0 <= period <= 1000000):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "1006h は 0-1,000,000 μs")
        self.sync_period_us = period
```

- [ ] **Step 4: `RealtimeBridge` に SYNC producer を実装する**

`omsim/node/realtime_bridge.py` の `_TpdoRuntime` の下に追加:

```python
class _SyncProducerState(object):
    def __init__(self):
        self.next_due = None
```

`RealtimeBridge.__init__`/`attach` に追記:

```python
        self._sync_producer = {}
```

```python
        self._sync_producer[model.node_id] = _SyncProducerState()
```

`step()` の先頭に SYNC producer の判定を追加:

```python
    def step(self, node_id, model, network, od, sim_time):
        self._maybe_send_sync(node_id, model, network, sim_time)
        runtimes = self._tpdo_runtime[node_id]
        ...  # 既存の TPDO 判定はそのまま

    def _maybe_send_sync(self, node_id, model, network, sim_time):
        state = self._sync_producer[node_id]
        if not (model.sync_producer_enabled and model.sync_period_us > 0):
            state.next_due = None
            return
        period_seconds = model.sync_period_us / 1e6
        if state.next_due is None:
            state.next_due = sim_time
        if sim_time >= state.next_due:
            network.send_message(model.sync_cob_id & 0x7FF, [])
            state.next_due = sim_time + period_seconds
```

- [ ] **Step 5: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_driver_sync.py tests/unit/test_realtime_bridge.py -v"`
Expected: 全 passed

`tests/integration/test_pdo_over_vcan.py` に SYNC producer の結合テストを追記:

```python
def test_sync_producer_transmits_periodically(stepped_sim, master):
    import can

    node_id = 1
    model = stepped_sim.models[node_id]
    model.write_object(0x1005, 0, 0x80 | (1 << 30))
    model.write_object(0x1006, 0, 5000)  # 5ms 周期

    bus = can.interface.Bus(channel="vcan0", interface="socketcan",
                             can_filters=[{"can_id": 0x80, "can_mask": 0x7FF}])
    try:
        for _ in range(20):
            stepped_sim.step()
        msg = bus.recv(timeout=1.0)
        assert msg is not None
        assert msg.arbitration_id == 0x80
    finally:
        bus.shutdown()
```

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && pgrep -af 'omsim.apps'; python3 -m pytest tests/integration/test_pdo_over_vcan.py -v"`
Expected: 全 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed

- [ ] **Step 6: コミット**

```bash
git add omsim/driver/model.py omsim/node/realtime_bridge.py omsim/sim/manager.py tests/unit/test_driver_sync.py tests/integration/test_pdo_over_vcan.py
git commit -m "feat: SYNC producer/consumer (1005h/1006h) を実装する"
```

---

## Task 11: node guarding（100Ch/100Dh）と Heartbeat consumer（1016h）を実装する

**Files:**
- Modify: `omsim/driver/model.py`
- Modify: `omsim/driver/alarm_model.py`
- Modify: `omsim/node/realtime_bridge.py`
- Test: `tests/unit/test_driver_guard_heartbeat.py`（新規）
- Test: `tests/integration/test_guard_heartbeat_over_vcan.py`（新規）

**Interfaces:**
- Consumes: `omsim/driver/state_machine.py` の `State`（NMT 状態は `canopen.NmtSlave` 側にあるため、node 層で文字列 → コードの対応表を持つ）
- Produces:
  - 新規 SDO オブジェクト `100Ch`（Guard time）/ `100Dh`（Life time factor）
  - `1016h` sub1 が実際に Heartbeat consumer として機能する（従来は値の保持のみのスタブだった）
  - `DriverModel.on_heartbeat_received(node_id, sim_time)`
  - `AlarmModel.EMCY_HEARTBEAT_ERROR = 0x8130`
  - `RealtimeBridge` が node guarding の RTR に応答し、Heartbeat consumer 対象ノードのフレームを検知する

### なぜこれをやるか

**node guarding**: 4.2.1 実測のとおり、生死判定（RTR タイムアウト検出）は NMT master の責務。スレーブ（omsim）の責務は `100Ch`/`100Dh` の値の保持と、RTR に対する `(toggle<<7) | NMT状態` の 1 バイト応答のみ。

**Heartbeat consumer**: `1016h` は現在「値の保持のみ」のスタブ（P2 で `1017h`（producer）は実働と確認済みだが `1016h`（consumer）は未実装のまま）。ここで、指定ノードの Heartbeat が指定時間内に届かなければ EMCY `8130h`（"Node guarding error or heartbeat error"）を発行する実装に置き換える。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_driver_guard_heartbeat.py`:

```python
from omsim.driver.alarm_model import EMCY_HEARTBEAT_ERROR
from omsim.driver.model import DriverModel


def test_default_guard_time_and_life_time_factor_are_zero():
    model = DriverModel(node_id=1)
    assert model.read_object(0x100C) == 0
    assert model.read_object(0x100D) == 0


def test_write_guard_time_and_life_time_factor():
    model = DriverModel(node_id=1)
    model.write_object(0x100C, 0, 100)
    model.write_object(0x100D, 0, 3)
    assert model.guard_time_ms == 100
    assert model.life_time_factor == 3


def test_configuring_heartbeat_consumer_parses_node_id_and_time():
    model = DriverModel(node_id=1)
    # sub1 raw = (node_id << 16) | time_ms
    model.write_object(0x1016, 1, (2 << 16) | 500)
    assert model.heartbeat_consumer_node_id == 2
    assert model.heartbeat_consumer_time_ms == 500


def test_heartbeat_consumer_raises_alarm_after_timeout():
    model = DriverModel(node_id=1)
    model.write_object(0x1016, 1, (2 << 16) | 500)
    for _ in range(600):  # 600ms 分ステップを進める (何も heartbeat を受けない)
        model.step(0.001)
    assert model.alarms.is_active
    assert model.alarms.error_code == EMCY_HEARTBEAT_ERROR


def test_heartbeat_consumer_does_not_raise_before_timeout():
    model = DriverModel(node_id=1)
    model.write_object(0x1016, 1, (2 << 16) | 500)
    for _ in range(400):
        model.step(0.001)
    assert not model.alarms.is_active


def test_receiving_heartbeat_resets_the_reference_time():
    model = DriverModel(node_id=1)
    model.write_object(0x1016, 1, (2 << 16) | 500)
    for _ in range(400):
        model.step(0.001)
    model.on_heartbeat_received(node_id=2, sim_time=model.sim_time)
    for _ in range(400):  # 合計 800ms 経過したが、400ms 前に受信をリセットしたのでまだ猶予内
        model.step(0.001)
    assert not model.alarms.is_active


def test_heartbeat_consumer_disabled_when_node_id_is_zero():
    model = DriverModel(node_id=1)
    model.write_object(0x1016, 1, 0)  # node_id=0 は無効化
    for _ in range(2000):
        model.step(0.001)
    assert not model.alarms.is_active


def test_heartbeat_from_unrelated_node_is_ignored():
    model = DriverModel(node_id=1)
    model.write_object(0x1016, 1, (2 << 16) | 500)
    model.on_heartbeat_received(node_id=3, sim_time=0.0)  # 監視対象ではない
    for _ in range(600):
        model.step(0.001)
    assert model.alarms.is_active  # node 3 の受信は無視されるので、依然としてタイムアウトする
```

`tests/integration/test_guard_heartbeat_over_vcan.py`:

```python
import time

import can
import pytest

pytestmark = pytest.mark.vcan


def test_node_guard_rtr_gets_toggled_response(stepped_sim, master):
    node_id = 1
    bus = can.interface.Bus(channel="vcan0", interface="socketcan")
    try:
        request = can.Message(arbitration_id=0x700 + node_id, is_remote_frame=True,
                               is_extended_id=False, dlc=0)
        first_bytes = []
        for _ in range(2):
            bus.send(request)
            time.sleep(0.05)
            stepped_sim.step()
            msg = bus.recv(timeout=1.0)
            assert msg is not None
            assert msg.arbitration_id == 0x700 + node_id
            first_bytes.append(msg.data[0])
        # 2 回とも Pre-operational (0x7F) だが toggle bit (0x80) が反転しているはず。
        assert (first_bytes[0] & 0x7F) == 0x7F
        assert (first_bytes[0] & 0x80) != (first_bytes[1] & 0x80)
    finally:
        bus.shutdown()
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_driver_guard_heartbeat.py -q 2>&1 | tail -30"`
Expected: FAIL（`100Ch`/`100Dh` が abort、`EMCY_HEARTBEAT_ERROR` が無い）

- [ ] **Step 3: `alarm_model.py` に EMCY コードを追加する**

`omsim/driver/alarm_model.py` の定数に追加:

```python
EMCY_HEARTBEAT_ERROR = 0x8130  # HP-5143E 4.5 (p23): Node guarding error or heartbeat error
```

- [ ] **Step 4: `DriverModel` に guard/heartbeat consumer を実装する**

`omsim/driver/model.py` の `__init__` に追加:

```python
        self.guard_time_ms = 0
        self.life_time_factor = 0
        self.heartbeat_consumer_node_id = 0
        self.heartbeat_consumer_time_ms = 0
        self._heartbeat_consumer_reference_time = None
```

`import` に追加:

```python
from omsim.driver.alarm_model import EMCY_HEARTBEAT_ERROR
```

`step()` の末尾（quick-stop-active の判定の後）に追加:

```python
        self._check_heartbeat_consumer()
```

クラス本体に追加:

```python
    def _check_heartbeat_consumer(self):
        if not self.heartbeat_consumer_node_id or not self.heartbeat_consumer_time_ms:
            return
        if self._heartbeat_consumer_reference_time is None:
            return
        elapsed_ms = (self.sim_time - self._heartbeat_consumer_reference_time) * 1000.0
        if elapsed_ms > self.heartbeat_consumer_time_ms:
            self.alarms.raise_alarm(
                alarm_code=0, emcy_code=EMCY_HEARTBEAT_ERROR, error_register=0x11)

    def on_heartbeat_received(self, node_id, sim_time):
        """Heartbeat consumer が監視している node_id からのフレーム受信を伝える。

        node/realtime_bridge.py から呼ばれる (can 依存を持ち込まないための窓口)。
        """
        if node_id != self.heartbeat_consumer_node_id:
            return
        self._heartbeat_consumer_reference_time = sim_time
        if self.alarms.error_code == EMCY_HEARTBEAT_ERROR and self.alarms.is_active:
            self.alarms.set_cause_cleared(True)
            self.alarms.reset()

    @router.reader(0x100C)
    def _read_guard_time(self, sub):
        return self.guard_time_ms

    @router.writer(0x100C)
    def _write_guard_time(self, sub, value):
        time_ms = int(value)
        if not (0 <= time_ms <= 65535):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "100Ch は 0-65535")
        self.guard_time_ms = time_ms

    @router.reader(0x100D)
    def _read_life_time_factor(self, sub):
        return self.life_time_factor

    @router.writer(0x100D)
    def _write_life_time_factor(self, sub, value):
        factor = int(value)
        if not (0 <= factor <= 255):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "100Dh は 0-255")
        self.life_time_factor = factor
```

既存の `1016h` の stub reader/writer（`_read_consumer_heartbeat_time`/`_write_consumer_heartbeat_time`、`stub="P3: Heartbeat consumer 未実装。値の保持のみ"`）を次に置き換える（`stub=` 引数を外し、実際の配線を行う）:

```python
    @router.reader(0x1016, 1)
    def _read_consumer_heartbeat_time(self, sub):
        return self.consumer_heartbeat_config

    @router.writer(0x1016, 1)
    def _write_consumer_heartbeat_time(self, sub, value):
        raw = int(value) & 0xFFFFFFFF
        self.consumer_heartbeat_config = raw
        self.heartbeat_consumer_node_id = (raw >> 16) & 0xFF
        self.heartbeat_consumer_time_ms = raw & 0xFFFF
        self._heartbeat_consumer_reference_time = (
            self.sim_time if self.heartbeat_consumer_node_id and self.heartbeat_consumer_time_ms
            else None)
```

- [ ] **Step 5: `RealtimeBridge` に node guarding 応答と Heartbeat consumer 検知を追加する**

`omsim/node/realtime_bridge.py` の先頭付近に NMT 状態コードの対応表を追加（`canopen.NmtBase.state` は文字列を返すため、こちら側で数値へ変換する。私設の対応表を持つのは、`canopen` 内部の private 属性 `node.nmt._state` に依存しないため）:

```python
_NMT_STATE_TO_CODE = {
    "OPERATIONAL": 0x05,
    "STOPPED": 0x04,
    "PRE-OPERATIONAL": 0x7F,
}
```

`_NodeListener.__init__` にコンストラクタ引数を追加:

```python
    def __init__(self, node, model, od, queue, sync_counter):
        self._node = node
        self._model = model
        self._od = od
        self._queue = queue
        self._sync_counter = sync_counter
        self._guard_toggle = False
```

`on_message_received` に RTR / Heartbeat 検知を追加:

```python
    def on_message_received(self, msg):
        if getattr(msg, "is_error_frame", False):
            return
        can_id = msg.arbitration_id
        is_rtr = getattr(msg, "is_remote_frame", False)

        if not is_rtr and can_id == (self._model.sync_cob_id & 0x7FF):
            self._sync_counter.notify()
            return

        if is_rtr and can_id == 0x700 + self._model.node_id:
            self._respond_node_guard()
            return

        watch_node_id = self._model.heartbeat_consumer_node_id
        if not is_rtr and watch_node_id and can_id == 0x700 + watch_node_id:
            # Heartbeat/boot-up は 1 バイトの NMT 状態コードのみを積む
            # (4.2.2/4.3 実測)。sim_time は step() 側で管理しているため、
            # ここでは「今受信した」ことだけを model に伝える。
            self._model.on_heartbeat_received(watch_node_id, self._model.sim_time)
            return

        if not is_rtr:
            self._handle_rpdo(can_id, bytes(msg.data))

    def _respond_node_guard(self):
        state_code = _NMT_STATE_TO_CODE.get(self._node.nmt.state)
        if state_code is None:
            return
        byte0 = (0x80 if self._guard_toggle else 0x00) | state_code
        self._guard_toggle = not self._guard_toggle
        self._node.network.send_message(0x700 + self._model.node_id, [byte0])
```

`RealtimeBridge._make_listener`/`attach` の呼び出しを `_NodeListener(node, model, od, queue, sync_counter)` に合わせて更新する（`node` を渡すよう変更）:

```python
    def _make_listener(self, node, model, od, queue, sync_counter):
        return _NodeListener(node, model, od, queue, sync_counter)

    def attach(self, node, model, od, queue, sync_counter):
        listener = self._make_listener(node, model, od, queue, sync_counter)
        ...
```

（Task 8 で定義した `_make_listener(self, model, od, queue, sync_counter, node_id)` のシグネチャを変更するため、`tests/unit/test_realtime_bridge.py` の `make_listener` ヘルパーで `bridge._make_listener(...)` を呼んでいる箇所も **`node` の代わりに `node.nmt.state` を差し替え可能な軽量フェイクノード**を渡す形に更新する必要がある。次の Step で修正する。）

- [ ] **Step 6: 既存テストのフェイクノードを更新し、テストを通す**

`tests/unit/test_realtime_bridge.py` の `make_listener` ヘルパーを更新する:

```python
class FakeNmt(object):
    def __init__(self, state="PRE-OPERATIONAL"):
        self.state = state


class FakeNode(object):
    def __init__(self, state="PRE-OPERATIONAL"):
        self.nmt = FakeNmt(state)
        self.network = None  # node guarding のテストでは FakeNetwork を後付けする


def make_listener(node_id=1):
    od = load_eds(DEFAULT_EDS_PATH)
    model = DriverModel(node_id=node_id)
    queue = CommandQueue()
    sync_counter = SyncCounter()
    bridge = RealtimeBridge()
    node = FakeNode()
    listener = bridge._make_listener(node, model, od, queue, sync_counter)
    return listener, model, queue, sync_counter, node
```

既存の 7 個のテスト関数のシグネチャ（`listener, model, queue, _sync = make_listener()`）を `listener, model, queue, _sync, _node = make_listener()` に合わせて更新する。

`tests/unit/test_realtime_bridge.py` の末尾に node guarding のテストを追加:

```python
def test_node_guard_rtr_responds_with_toggled_state_byte():
    listener, _model, _queue, _sync, node = make_listener()
    node.network = FakeNetwork()
    listener._respond_node_guard()
    listener._respond_node_guard()
    assert len(node.network.sent) == 2
    first_byte = node.network.sent[0][1][0]
    second_byte = node.network.sent[1][1][0]
    assert (first_byte & 0x7F) == 0x7F  # PRE-OPERATIONAL
    assert (first_byte & 0x80) != (second_byte & 0x80)


def test_heartbeat_from_watched_node_notifies_the_model():
    import can

    listener, model, _queue, _sync, _node = make_listener()
    model.write_object(0x1016, 1, (2 << 16) | 500)
    msg = can.Message(arbitration_id=0x702, data=[0x7F], is_extended_id=False)
    listener.on_message_received(msg)
    assert model._heartbeat_consumer_reference_time == model.sim_time
```

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_realtime_bridge.py tests/unit/test_driver_guard_heartbeat.py -v"`
Expected: 全 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && pgrep -af 'omsim.apps'; python3 -m pytest tests/integration/test_guard_heartbeat_over_vcan.py -v"`
Expected: PASS

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed

- [ ] **Step 7: コミット**

```bash
git add omsim/driver/model.py omsim/driver/alarm_model.py omsim/node/realtime_bridge.py tests/unit/test_realtime_bridge.py tests/unit/test_driver_guard_heartbeat.py tests/integration/test_guard_heartbeat_over_vcan.py
git commit -m "feat: node guarding の RTR 応答と Heartbeat consumer (1016h) を実装する"
```

---

## Task 12: `1003h` エラー履歴を CiA301 準拠に是正する

**Files:**
- Modify: `omsim/driver/alarm_model.py`
- Modify: `omsim/driver/errors.py`
- Modify: `omsim/driver/model.py`
- Test: `tests/unit/test_alarm_model.py`（変更）
- Test: `tests/unit/test_driver_objects_p1.py`（該当テストを確認・必要なら変更）

**Interfaces:**
- Consumes: なし
- Produces:
  - `AlarmModel.raise_alarm()` が `1003h` 用に **EMCY エラーコード（下位16bit）| メーカ固有コード（上位16bit）** を履歴へ積む（CiA301 Pre-defined error field の形式）
  - `ABORT_NO_DATA = 0x08000024`（`errors.py`）
  - `_read_error_field` が、まだ記録の無い sub-index を読むと `ABORT_NO_DATA` で abort する（従来は `0` を返していた）

### なぜこれをやるか

**段数について**: EDS の `1003h` は `SubNumber=11`（`sub0` + `sub1`〜`sub10` = 10 個の実エントリ）。設計書 5.1 の「`1003h`(11 sub)」・「エラー履歴 11 段」はこの `SubNumber=11`（sub-index の総数）を指しており、実エントリ数は 10 で正しい。現在の `AlarmModel(history_size=10)` は既に EDS と一致しているため、**段数自体は変更しない**（進捗台帳の「現在10」という記述は sub-index の総数と実エントリ数を混同した誤記と判断し、EDS を正として扱う）。

**フォーマットについて**: 現在 `1003h` の各エントリにはメーカ固有アラームコード（例: 過負荷 `0x30`）がそのまま入っている。CiA301 の Pre-defined error field は「下位 16bit = EMCY error code、上位 16bit = メーカ固有情報」という 32bit 値であるべき（4.5 実測: 「The error code is filled in at the location of Pre-defined error field (1003h)」であり、ここでの error code は EMCY メッセージの error code フィールドと同じもの）。

**abort について**: `_read_error_field` は範囲外（記録がまだ無い）sub-index に対して `0` を返していたが、CiA301 では「データが無い」ことは abort で表現するのが正しい。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_alarm_model.py` を次のように変更する（`test_raising_appends_to_history_newest_first` と `test_second_alarm_while_active_is_ignored` を書き換え、新規テストを追加）:

```python
def test_raising_appends_packed_cia301_value_to_history():
    model = AlarmModel()
    model.raise_alarm(alarm_code=0x30, emcy_code=0x2310)
    # 下位16bit = EMCY code (0x2310)、上位16bit = メーカ固有 (0x30)
    assert model.history[0] == (0x30 << 16) | 0x2310


def test_raising_appends_to_history_newest_first():
    model = AlarmModel()
    model.raise_alarm(0x30, 0x2310)
    model.set_cause_cleared(True)
    model.reset()
    model.raise_alarm(0x31, 0x2311)
    assert model.history[0] == (0x31 << 16) | 0x2311
    assert model.history[1] == (0x30 << 16) | 0x2310


def test_second_alarm_while_active_is_ignored():
    model = AlarmModel()
    model.raise_alarm(0x30, 0x2310)
    model.raise_alarm(0x31, 0x2311)
    assert model.active_alarm == 0x30  # active_alarm はメーカ固有コードのまま (Web 表示用)
    assert model.history == [(0x30 << 16) | 0x2310]


def test_manufacturer_specific_code_with_zero_is_packed_as_zero_upper_bits():
    """通信エラー系 (Heartbeat 断など) は EMCY code 自体がそのままの値で、
    メーカ固有部分を持たない。上位16bit は 0 になる。"""
    model = AlarmModel()
    model.raise_alarm(alarm_code=0, emcy_code=0x8130)
    assert model.history[0] == 0x8130
```

`test_history_is_bounded` はそのまま（`history_size=3` を明示するテストで、フォーマット変更の影響を受けない）。

`tests/unit/test_driver_objects_p1.py` を開き、`1003h` の履歴/範囲外読みに関するテストがあれば内容を確認する。既存に「範囲外は 0 を返す」というアサーションがあれば、次のように書き換える:

```python
def test_reading_unrecorded_error_field_sub_index_aborts():
    from omsim.driver.errors import ABORT_NO_DATA, ObjectAccessError
    from omsim.driver.model import DriverModel

    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError) as exc:
        model.read_object(0x1003, 1)  # まだ 1 件もアラームが無い
    assert exc.value.abort_code == ABORT_NO_DATA
```

（既存テストに同等のものが無ければ、`tests/unit/test_driver_objects_p1.py` の末尾に新規追加する。）

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_alarm_model.py tests/unit/test_driver_objects_p1.py -q 2>&1 | tail -30"`
Expected: FAIL（現在は生のメーカ固有コードを積み、範囲外は 0 を返す）

- [ ] **Step 3: 実装する**

`omsim/driver/errors.py` に追加:

```python
ABORT_NO_DATA = 0x08000024
```

`omsim/driver/alarm_model.py` の `raise_alarm` を変更する:

```python
    def raise_alarm(self, alarm_code, emcy_code, error_register=0x01):
        if self.is_active:
            return
        self.active_alarm = alarm_code
        self.error_code = emcy_code
        self.error_register = error_register
        self._cause_cleared = False
        # CiA301 Pre-defined error field: 下位16bit = EMCY error code、
        # 上位16bit = メーカ固有情報。1003h に積むのはこの形式であって、
        # メーカ固有アラームコードそのものではない (P2 最終レビュー指摘)。
        packed = (emcy_code & 0xFFFF) | ((alarm_code & 0xFFFF) << 16)
        self._history.appendleft(packed)
        self._pending_emcy.append((emcy_code, error_register))
```

`omsim/driver/model.py` の `_read_error_field` を変更する:

```python
    def _read_error_field(self, sub):
        history = self.alarms.history
        if sub > len(history):
            raise ObjectAccessError(
                ABORT_NO_DATA,
                "1003h:{:02X} はまだ記録がありません".format(sub))
        return history[sub - 1]
```

import に `ABORT_NO_DATA` を追加する:

```python
from omsim.driver.errors import (
    ABORT_DEVICE_STATE,
    ABORT_NO_DATA,
    ABORT_VALUE_RANGE,
    NotImplementedObjectError,
    ObjectAccessError,
)
```

- [ ] **Step 4: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_alarm_model.py tests/unit/test_driver_objects_p1.py -v"`
Expected: 全 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed（`test_realtime_bridge.py::test_heartbeat_from_watched_node_notifies_the_model` など、Task 11 で追加した Heartbeat 断アラームのテストが `emcy_code=EMCY_HEARTBEAT_ERROR, alarm_code=0` で呼ばれているため、`1003h` には `0x8130` がそのまま積まれることを確認する）

- [ ] **Step 5: コミット**

```bash
git add omsim/driver/alarm_model.py omsim/driver/errors.py omsim/driver/model.py tests/unit/test_alarm_model.py tests/unit/test_driver_objects_p1.py
git commit -m "fix: 1003h エラー履歴を CiA301 準拠 (EMCYコード+メーカ固有のパック形式、範囲外はabort) に是正する"
```

---

## Task 13: Web への反映と P3 総仕上げ

**Files:**
- Modify: `README.md`
- Test: 手動確認（controller が Playwright で実施）+ 全テスト

**Interfaces:**
- Consumes: これまでの全成果
- Produces: PDO/SYNC/Heartbeat/node guarding が Web の CAN ログ・ステータスモニタに実際に映ることの確認、`omsim --coverage`/`--list-stubs` の実測記録

### なぜこれをやるか

P2 は「Web の中身」を作ったが、`omsim` 自身の送信フレーム（Task 3 で解消済み）と PDO/SYNC/HB/node guarding（本計画の中身）は当時は存在しなかった。ここで両方が揃った状態を実機で確認する。

- [ ] **Step 1: 網羅率を実測する**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m omsim.apps.omsim_main --coverage | head -12"`

実測出力（総数・実装済み・値の保持のみ・未実装の件数）を報告書に記録する。P2 終了時点は「総数 266 / 実装済み 41 / 値の保持のみ 11 / 未実装 214」だった。Task 6/7/10/11/12 で 1400h-1403h(各3sub)/1600h-1603h(各5sub)/1800h-1803h(各5sub)/1A00h-1A03h(各5sub)/1005h/1006h/100Ch/100Dh/1016h(1sub、スタブ解消) が新規実装されるため、実装済み件数が相応に増えているはずである。

- [ ] **Step 2: スタブ一覧を実測する**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m omsim.apps.omsim_main --list-stubs"`

`0x1016:01` がスタブ一覧から消えている（Task 11 で実装済みになったため）ことを確認する。実測出力を報告書に記録する。

- [ ] **Step 3: シナリオで PDO/SYNC/HB/node guarding を動かしながら Web を目視確認する（controller 作業）**

以下のシナリオ YAML を用意する（`tests/scenarios/pdo_sync_demo.yaml`、新規）:

```yaml
name: pdo_sync_demo
nodes: [1]
steps:
  - kind: nmt
    nodes: [1]
    value: start
  - kind: sdo_write
    nodes: [1]
    index: 0x1800
    sub: 2
    value: 1          # TPDO1 を「毎 SYNC で送信」に変更
  - kind: sdo_write
    nodes: [1]
    index: 0x1017
    sub: 0
    value: 200         # Heartbeat producer を 200ms 周期で有効化
  - kind: sdo_write
    nodes: [1]
    index: 0x6040
    sub: 0
    value: 0x0006
  - kind: sdo_write
    nodes: [1]
    index: 0x6040
    sub: 0
    value: 0x0007
  - kind: sdo_write
    nodes: [1]
    index: 0x6040
    sub: 0
    value: 0x000F
  - kind: pdo_send
    nodes: [1]
    cob_id: 0x80
    data: []            # SYNC を手動送信 (マスタ役として)
  - kind: wait
    nodes: [1]
    seconds: 1.0
```

Run（VM 上で web 付きの omsim を起動しつつ、別シェルでシナリオを流す）:

```bash
rtk proxy ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && (nohup python3 -m omsim.apps.omsim_main --node 1 --web-port 8080 --web-host 0.0.0.0 --duration 60 > /tmp/web.log 2>&1 &) ; sleep 3; python3 -m omsim.apps.scenario tests/scenarios/pdo_sync_demo.yaml | tail -10"
```

controller が Windows のブラウザで `http://192.168.33.10:8080/` を開き、次を Playwright で確認する:
- CAN ログに `701`（boot-up または Heartbeat）に加え、`181`（TPDO1）と `80`（SYNC、マスタ側から送っているため受信フレームとしても映る）が **tx/rx を問わず**現れること
- ステータスモニタの Statusword ビットが `0x0637`（operation-enabled 相当）に変化すること
- コンソールエラーが 0 件であること

確認した実測（スクリーンショットまたは CAN ログのテキスト）を報告書に残す。

- [ ] **Step 4: README に P3 の内容を追記する**

`README.md` に次を追記する（既存の節は消さない）:

- **PDO**: `1400h`-`1403h`/`1600h`-`1603h`（RPDO）、`1800h`-`1803h`/`1A00h`-`1A03h`（TPDO）が動的マッピングに対応
- **SYNC**: `1005h` の bit30 で producer/consumer を切替可能。`1006h` で周期（μs）を設定
- **Heartbeat consumer**: `1016h` sub1 に `(node_id<<16)|time_ms` を書くと、指定ノードの Heartbeat 断で EMCY `8130h` を発行
- **node guarding**: `100Ch`/`100Dh` の値を保持し、RTR に `(toggle<<7)|NMT状態` で応答（生死判定自体はマスタの責務）
- **既知の制限**: PDO マッピングはバイト境界のみサポート（ビット単位のサブバイトパッキングは対象外）。SYNC 受信の検出粒度は 1ms（step 周期）単位

- [ ] **Step 5: 最終確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && pgrep -af 'omsim.apps'; python3 -m pytest -q 2>&1 | tail -3"`
Expected: 全 passed、SKIP 0

Run（3 回連続で flaky が無いことを確認）: 上記を 3 回繰り返し、毎回同一件数の passed になることを確認する。

- [ ] **Step 6: コミット**

```bash
git add README.md tests/scenarios/pdo_sync_demo.yaml
git commit -m "docs: P3 (PDO/SYNC/Heartbeat consumer/node guarding) の使い方を README に追加"
```

---

## 完了条件

- [ ] `python3 -m pytest -q` が VM 上で全 passed（SKIP 0）、3 回連続で同一結果
- [ ] `CommandQueue` が `(index,sub)` 単位の last-write-wins + `maxlen` + `trigger`（immediate/sync）に対応している
- [ ] omsim 自身の送信フレーム（SDO 応答・boot-up・Heartbeat・EMCY・PDO・SYNC・node guarding 応答）が全て CAN ログに記録される
- [ ] `validate_object` が deepcopy ではなく必要な入れ子だけの部分コピーで動作し、`test_shadow_isolation_holds_for_every_registered_writer` が全 writer について隔離を確認している
- [ ] RPDO/TPDO 4+4 が動的マッピングに対応し、transmission type（sync/cyclic-Nth/RTR-only/event-driven）ごとに正しく送受信される
- [ ] SYNC producer/consumer が `1005h`/`1006h` で設定可能
- [ ] Heartbeat consumer（`1016h`）が実働し、node guarding（`100Ch`/`100Dh`）が RTR に正しく応答する
- [ ] `1003h` が CiA301 準拠（EMCY コード + メーカ固有のパック形式）で、範囲外の読み出しは abort する
- [ ] `omsim --coverage`/`--list-stubs` の実測結果が報告書に記録されている
- [ ] controller が実ブラウザで PDO/SYNC/Heartbeat が Web の CAN ログとステータスに映ることを確認済み

## 次のフェーズ

P4（pp/hm/tq モード、停止動作、option code 群、touch probe、リミット）は別計画。本計画で実装した PDO マッピング基盤（`607Ah` Target position など）は、P4 で pp モードの writer が実装され次第、追加のマッピング変更なしにそのまま動くようになる。

P3 で意図的に対象外としたもの:
- ビット単位のサブバイト PDO マッピング（EDS の既定マッピングが全てバイト境界のため対象外と判断）
- SYNC 受信の 1ms 未満の粒度での多重カウント
- node guarding のマスタ側の生死判定ロジック自体（スレーブの責務ではないため実装しない）
- PDO 通信/マッピングパラメータの NMT 状態（Pre-operational/Operational）によるアクセス制御（「PDO は Pre-operational 状態で設定する」という運用上の前提はあるが、omsim 側での強制は行わない）
