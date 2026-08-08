# オリエンタルモーター CAN 通信シミュレータ P0-P1 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BLVD-KRD ドライバを CANopen スレーブとして再現するシミュレータの土台を作り、2 台同時に動かして pitakuru の oriental_motor ノードを実機なしで繋げられる状態にする。

**Architecture:** `canopen` ライブラリの `LocalNode` が CANopen 通信層（SDO サーバ / NMT スレーブ / Heartbeat / EMCY / OD）を担い、その read/write コールバック越しに自作の `DriverModel` がドライバ挙動を持つ。`DriverModel` は `can` も `canopen` も import せず、`read_object` / `write_object` / `step` / `snapshot` の 4 メソッドだけを外に出すため、CAN 抜きで pytest から直接叩ける。バスは SocketCAN の `vcan0`。

**Tech Stack:** Python 3.8 / canopen 2.4.1 / python-can 4.5.0 / pytest 8.3.5 / PyYAML 6.0.2 / SocketCAN (vcan) / Vagrant Ubuntu 20.04

**設計書:** `docs/superpowers/specs/2026-08-08-oriental-motor-simulator-design.md`

**対象フェーズ:** P0（骨格・SDO 疎通・シナリオ最小版・CAN ログ）と P1（CiA402 ステートマシン・pv・単位系・アラーム基礎・2 ノード独立性・pitakuru 疎通）。P2 以降は別計画。

## Global Constraints

- Python は **3.8**（Vagrant VM の Ubuntu 20.04 既定）。3.9 以降の構文（`list[int]` の実行時評価、`dict | dict`、`match`）を使わない。型注釈は `typing` から import し、必要なら `from __future__ import annotations` を先頭に置く。
- 依存は完全に pin する: `canopen==2.4.1` / `python-can==4.5.0` / `pytest==8.3.5` / `PyYAML==6.0.2`。
- **`omsim/driver/` 配下は `can` と `canopen` を import してはならない。** これを守れているかを自動テストで検証する（Task 5）。
- シミュレーションのステップは **1ms 固定**（`SimClock.STEP_SECONDS = 0.001`）。
- **複数ノードを 1 プロセスで同時に動かす。** `DriverModel` はインスタンスごとに完全独立な状態を持ち、クラス変数やモジュールグローバルで状態を共有しない。台数は `--node` の指定数で決まり、2 台に固定しない。
- 仕様の正本は `docs/oriental_motor/HP-5143E.pdf`（CANopen プロファイル）と `docs/oriental_motor/HP-5141J.pdf`（機能編）。実装中に判断が必要になったらこの 2 冊の該当ページを開いて確認し、参照ページをコード内のコメントに残す。
- **git commit に Claude の署名（`Co-Authored-By: Claude` 等）を付けない。** コミットは `Kousuke Takeuchi` 名義のみ。
- 未実装の挙動は `NotImplementedError` を投げる。黙って既定値を返してはならない（嘘の合格が最悪の結果）。
- EDS は起動時に差し替えられる。実装の基準は `BLVD-KRD_CANopen_V400.eds`。

---

## ファイル構成

このフェーズで作るファイルと責務。1 ファイル 1 責務を守り、大きくなったら分割する。

| ファイル | 責務 |
|---|---|
| `pyproject.toml` | パッケージ定義とコンソールスクリプト 4 本 |
| `requirements.txt` | 依存の pin |
| `omsim/__init__.py` | バージョン定義のみ |
| `omsim/driver/errors.py` | `ObjectAccessError`（abort コードを持つ例外）。`canopen` に依存しない |
| `omsim/driver/objects.py` | オブジェクトインデックスの定数と `ObjectRouter`（index/sub → ハンドラ登録） |
| `omsim/driver/model.py` | `DriverModel`。4 メソッドの窓口とサブモジュールの組み立て |
| `omsim/driver/state_machine.py` | `Cia402StateMachine`。`6040h` / `6041h` と option code |
| `omsim/driver/units.py` | `UnitConverter`。`6091h` / `608Fh` / `60A8h` / `60A9h` |
| `omsim/driver/profile.py` | `TrapezoidProfile`。台形加減速と起動速度 |
| `omsim/driver/motor_plant.py` | `MotorPlant`。1 次遅れ追従・位置積分・トルク推定 |
| `omsim/driver/operation_pv.py` | `ProfileVelocityMode`。pv モードの運転 |
| `omsim/driver/alarm_model.py` | `AlarmModel`。アラーム発生・解除・履歴 |
| `omsim/node/eds.py` | EDS 読み込み |
| `omsim/node/od_bridge.py` | `LocalNode` のコールバックと `DriverModel` の接続 |
| `omsim/can/bus.py` | `canopen.Network` の生成と切断 |
| `omsim/sim/clock.py` | `SimClock`。1ms 固定ステップと実時間ペーシング |
| `omsim/sim/manager.py` | `NodeManager`。複数ノードの生成と一括 step |
| `omsim/sim/recorder.py` | `Recorder`。CAN フレームと状態を jsonl に記録 |
| `omsim/sim/decode.py` | CANopen フレームの人間可読デコード |
| `omsim/apps/omsim_main.py` | 本体 CLI |
| `omsim/apps/scenario.py` | シナリオランナー最小版 |
| `scripts/setup_vcan.sh` | `vcan0` 作成 |
| `scripts/omsim-vcan.service` | `vcan0` の systemd 永続化 |
| `tests/unit/**` | `driver/` の単体テスト（網羅の主戦場） |
| `tests/integration/**` | `vcan0` 越しのプロトコル結合テスト |
| `tests/scenarios/*.yaml` | シナリオ |

---

## Task 1: リポジトリ骨格と依存の pin

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `omsim/__init__.py`
- Create: `pytest.ini`
- Test: `tests/unit/test_package.py`

**Interfaces:**
- Consumes: なし
- Produces: `omsim.__version__` (str)。以降の全タスクは `omsim` パッケージ配下に置く。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_package.py`:

```python
import sys

import omsim


def test_version_is_exposed():
    assert isinstance(omsim.__version__, str)
    assert omsim.__version__ != ""


def test_runs_on_python_38_or_newer():
    assert sys.version_info >= (3, 8)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_package.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim'`

- [ ] **Step 3: 最小の実装**

`omsim/__init__.py`:

```python
__version__ = "0.1.0"
```

`requirements.txt`:

```
canopen==2.4.1
python-can==4.5.0
pytest==8.3.5
PyYAML==6.0.2
```

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=45"]
build-backend = "setuptools.build_meta"

[project]
name = "omsim"
version = "0.1.0"
description = "Oriental Motor BLVD-KRD CANopen driver simulator"
requires-python = ">=3.8"
dependencies = [
    "canopen==2.4.1",
    "python-can==4.5.0",
    "PyYAML==6.0.2",
]

[project.scripts]
omsim = "omsim.apps.omsim_main:main"
omsim-scenario = "omsim.apps.scenario:main"

[tool.setuptools.packages.find]
include = ["omsim*"]
```

`pytest.ini`:

```ini
[pytest]
testpaths = tests
markers =
    vcan: vcan0 が必要な結合テスト（無い環境では skip される）
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pip install -e . && python -m pytest tests/unit/test_package.py -v`
Expected: 2 passed

- [ ] **Step 5: コミット**

```bash
git add pyproject.toml requirements.txt pytest.ini omsim/__init__.py tests/unit/test_package.py
git commit -m "chore: omsim パッケージの骨格と依存 pin"
```

---

## Task 2: EDS ローダ

**Files:**
- Create: `omsim/node/__init__.py`
- Create: `omsim/node/eds.py`
- Test: `tests/unit/test_eds.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `load_eds(path: str) -> canopen.ObjectDictionary`
  - `DEFAULT_EDS_PATH: str` — `docs/oriental_motor/BLVD-KRD_CANopen_V400.eds` の絶対パス
  - `find_eds(name_or_path: str) -> str` — ファイル名だけ渡されたら `docs/oriental_motor/` から探す

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_eds.py`:

```python
import pytest

from omsim.node.eds import DEFAULT_EDS_PATH, find_eds, load_eds


def test_loads_v400_eds():
    od = load_eds(DEFAULT_EDS_PATH)
    assert 0x6040 in od
    assert 0x6041 in od
    assert 0x60FF in od
    assert 0x4148 in od


def test_manufacturer_parameter_defaults_match_eds():
    od = load_eds(DEFAULT_EDS_PATH)
    assert od[0x414B].default == 1
    assert od[0x415F].default == 10000
    assert od[0x4186].default == 3000
    assert od[0x41CA].default == 1
    assert od[0x4735].default == 1000


def test_find_eds_accepts_bare_filename():
    assert find_eds("BLVD-KRD_CANopen_V400.eds").endswith("BLVD-KRD_CANopen_V400.eds")


def test_find_eds_raises_on_unknown():
    with pytest.raises(FileNotFoundError):
        find_eds("does-not-exist.eds")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_eds.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.node'`

- [ ] **Step 3: 最小の実装**

`omsim/node/__init__.py`: 空ファイル

`omsim/node/eds.py`:

```python
"""EDS ファイルの読み込み。仕様の正本は docs/oriental_motor/*.eds。"""
import os

import canopen

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EDS_DIR = os.path.join(_REPO_ROOT, "docs", "oriental_motor")
DEFAULT_EDS_PATH = os.path.join(EDS_DIR, "BLVD-KRD_CANopen_V400.eds")


def find_eds(name_or_path):
    """パスならそのまま、ファイル名だけなら docs/oriental_motor/ から探す。"""
    if os.path.isfile(name_or_path):
        return os.path.abspath(name_or_path)
    candidate = os.path.join(EDS_DIR, name_or_path)
    if os.path.isfile(candidate):
        return candidate
    raise FileNotFoundError("EDS が見つかりません: {}".format(name_or_path))


def load_eds(path):
    return canopen.import_od(find_eds(path))
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_eds.py -v`
Expected: 4 passed

もし `test_manufacturer_parameter_defaults_match_eds` が落ちる場合は、`canopen` が EDS の `DefaultValue` を `default` ではなく `value` に入れている可能性がある。実際の属性を `python -c "from omsim.node.eds import *; od=load_eds(DEFAULT_EDS_PATH); print(od[0x414B].default, od[0x414B].value)"` で確認し、テストを実測に合わせて修正する（EDS の値は右辺の期待値のまま。どちらの属性に入るかだけが問題）。

- [ ] **Step 5: コミット**

```bash
git add omsim/node/__init__.py omsim/node/eds.py tests/unit/test_eds.py
git commit -m "feat: EDS ローダ"
```

---

## Task 3: SimClock（1ms 固定ステップ）

**Files:**
- Create: `omsim/sim/__init__.py`
- Create: `omsim/sim/clock.py`
- Test: `tests/unit/test_clock.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `SimClock.STEP_SECONDS: float = 0.001`
  - `SimClock(realtime: bool = True)`
  - `SimClock.tick_count: int` — 経過ステップ数
  - `SimClock.now: float` — シミュレーション時刻[秒]
  - `SimClock.advance() -> float` — 1 ステップ進めて `STEP_SECONDS` を返す
  - `SimClock.advance_for(seconds: float) -> int` — 指定秒数ぶんステップし、進めた回数を返す

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_clock.py`:

```python
from omsim.sim.clock import SimClock


def test_step_is_one_millisecond():
    assert SimClock.STEP_SECONDS == 0.001


def test_advance_increments_tick_and_time():
    clock = SimClock(realtime=False)
    assert clock.tick_count == 0
    assert clock.now == 0.0
    dt = clock.advance()
    assert dt == 0.001
    assert clock.tick_count == 1
    assert abs(clock.now - 0.001) < 1e-12


def test_advance_for_is_deterministic():
    clock = SimClock(realtime=False)
    assert clock.advance_for(1.0) == 1000
    assert clock.tick_count == 1000
    assert abs(clock.now - 1.0) < 1e-9


def test_time_does_not_drift_over_many_steps():
    clock = SimClock(realtime=False)
    clock.advance_for(60.0)
    assert clock.tick_count == 60000
    assert abs(clock.now - 60.0) < 1e-9
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_clock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.sim'`

- [ ] **Step 3: 最小の実装**

`omsim/sim/__init__.py`: 空ファイル

`omsim/sim/clock.py`:

```python
"""1ms 固定ステップの時計。now は tick_count から計算し、加算誤差を溜めない。"""
import time


class SimClock(object):
    STEP_SECONDS = 0.001

    def __init__(self, realtime=True):
        self.realtime = realtime
        self.tick_count = 0
        self._wall_start = time.monotonic()

    @property
    def now(self):
        return self.tick_count * self.STEP_SECONDS

    def advance(self):
        self.tick_count += 1
        if self.realtime:
            target = self._wall_start + self.now
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        return self.STEP_SECONDS

    def advance_for(self, seconds):
        steps = int(round(seconds / self.STEP_SECONDS))
        for _ in range(steps):
            self.advance()
        return steps
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_clock.py -v`
Expected: 4 passed

- [ ] **Step 5: コミット**

```bash
git add omsim/sim/__init__.py omsim/sim/clock.py tests/unit/test_clock.py
git commit -m "feat: 1ms 固定ステップの SimClock"
```

---

## Task 4: ObjectAccessError と ObjectRouter

**Files:**
- Create: `omsim/driver/__init__.py`
- Create: `omsim/driver/errors.py`
- Create: `omsim/driver/objects.py`
- Test: `tests/unit/test_object_router.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `ObjectAccessError(abort_code: int, message: str = "")` — 属性 `abort_code`
  - `ABORT_NOT_WRITABLE = 0x06010002` / `ABORT_VALUE_RANGE = 0x06090030` / `ABORT_NOT_IN_OD = 0x06020000` / `ABORT_DEVICE_STATE = 0x08000022`
  - `ObjectRouter()` — `.reader(index, sub=0)` / `.writer(index, sub=0)` デコレータ、`.read(owner, index, sub)`、`.write(owner, index, sub, value)`、`.has_reader(index, sub)`、`.has_writer(index, sub)`
  - `ObjectRouter.read` は登録が無ければ `None` を返す（OD 既定値へフォールスルーさせるため）
  - `ObjectRouter.write` は登録が無ければ `ObjectAccessError(ABORT_NOT_WRITABLE)` を投げる

`ObjectRouter` はクラス定義時にデコレータで表を作り、実行時は `owner`（`DriverModel` インスタンス）を渡して呼ぶ。これによりノードごとに状態が完全に独立する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_object_router.py`:

```python
import pytest

from omsim.driver.errors import ABORT_NOT_WRITABLE, ObjectAccessError
from omsim.driver.objects import ObjectRouter


class Fake(object):
    router = ObjectRouter()

    def __init__(self):
        self.stored = 7

    @router.reader(0x6041)
    def _read_status(self, sub):
        return self.stored

    @router.writer(0x6040)
    def _write_control(self, sub, value):
        self.stored = value


def test_read_dispatches_to_owner_instance():
    a, b = Fake(), Fake()
    b.stored = 99
    assert Fake.router.read(a, 0x6041, 0) == 7
    assert Fake.router.read(b, 0x6041, 0) == 99


def test_unregistered_read_returns_none():
    assert Fake.router.read(Fake(), 0x1008, 0) is None


def test_write_dispatches_and_isolates_instances():
    a, b = Fake(), Fake()
    Fake.router.write(a, 0x6040, 0, 15)
    assert a.stored == 15
    assert b.stored == 7


def test_unregistered_write_aborts_as_not_writable():
    with pytest.raises(ObjectAccessError) as exc:
        Fake.router.write(Fake(), 0x1008, 0, 1)
    assert exc.value.abort_code == ABORT_NOT_WRITABLE


def test_subindex_is_part_of_the_key():
    assert Fake.router.has_reader(0x6041, 0) is True
    assert Fake.router.has_reader(0x6041, 1) is False
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_object_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.driver'`

- [ ] **Step 3: 最小の実装**

`omsim/driver/__init__.py`: 空ファイル

`omsim/driver/errors.py`:

```python
"""driver 層の例外。canopen に依存しないため abort コードを整数で持つ。"""

ABORT_NOT_IN_OD = 0x06020000
ABORT_NOT_READABLE = 0x06010001
ABORT_NOT_WRITABLE = 0x06010002
ABORT_VALUE_RANGE = 0x06090030
ABORT_DEVICE_STATE = 0x08000022


class ObjectAccessError(Exception):
    def __init__(self, abort_code, message=""):
        super(ObjectAccessError, self).__init__(
            message or "SDO abort 0x{:08X}".format(abort_code)
        )
        self.abort_code = abort_code
```

`omsim/driver/objects.py`:

```python
"""オブジェクトインデックスから DriverModel のメソッドへの振り分け表。"""
from omsim.driver.errors import ABORT_NOT_WRITABLE, ObjectAccessError


class ObjectRouter(object):
    def __init__(self):
        self._readers = {}
        self._writers = {}

    def reader(self, index, sub=0):
        def decorate(func):
            self._readers[(index, sub)] = func
            return func

        return decorate

    def writer(self, index, sub=0):
        def decorate(func):
            self._writers[(index, sub)] = func
            return func

        return decorate

    def has_reader(self, index, sub=0):
        return (index, sub) in self._readers

    def has_writer(self, index, sub=0):
        return (index, sub) in self._writers

    def read(self, owner, index, sub):
        func = self._readers.get((index, sub))
        if func is None:
            return None
        return func(owner, sub)

    def write(self, owner, index, sub, value):
        func = self._writers.get((index, sub))
        if func is None:
            raise ObjectAccessError(ABORT_NOT_WRITABLE)
        func(owner, sub, value)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_object_router.py -v`
Expected: 5 passed

- [ ] **Step 5: コミット**

```bash
git add omsim/driver/__init__.py omsim/driver/errors.py omsim/driver/objects.py tests/unit/test_object_router.py
git commit -m "feat: ObjectRouter と ObjectAccessError"
```

---

## Task 5: DriverModel の窓口と層分離の自動検証

**Files:**
- Create: `omsim/driver/model.py`
- Test: `tests/unit/test_driver_model.py`
- Test: `tests/unit/test_layering.py`

**Interfaces:**
- Consumes: `ObjectRouter`, `ObjectAccessError`, `SimClock.STEP_SECONDS`
- Produces:
  - `DriverModel(node_id: int)`
  - `DriverModel.read_object(index: int, sub: int = 0) -> Optional[int]`
  - `DriverModel.write_object(index: int, sub: int = 0, value: int = 0) -> None`
  - `DriverModel.step(dt: float) -> None`
  - `DriverModel.snapshot() -> Dict[str, Any]` — 最低キー: `node_id`, `sim_time`
  - `DriverModel.sim_time: float`
  - このフェーズで扱うオブジェクト: `1008h`（装置名、読み専用、値 `"BLVD-KRD"`）

`1008h` を最初のハンドラにするのは、EDS の `const` を driver 側から返せることと「書けないものは abort する」ことを 1 つで確認できるため。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_driver_model.py`:

```python
import pytest

from omsim.driver.errors import ABORT_NOT_WRITABLE, ObjectAccessError
from omsim.driver.model import DriverModel


def test_reports_its_node_id():
    assert DriverModel(node_id=3).snapshot()["node_id"] == 3


def test_device_name_is_readable():
    assert DriverModel(node_id=1).read_object(0x1008) == "BLVD-KRD"


def test_device_name_is_not_writable():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x1008, 0, 1)
    assert exc.value.abort_code == ABORT_NOT_WRITABLE


def test_unhandled_object_reads_as_none():
    assert DriverModel(node_id=1).read_object(0x1018, 1) is None


def test_step_accumulates_sim_time():
    model = DriverModel(node_id=1)
    for _ in range(1000):
        model.step(0.001)
    assert abs(model.sim_time - 1.0) < 1e-9
    assert abs(model.snapshot()["sim_time"] - 1.0) < 1e-9


def test_two_models_do_not_share_state():
    a, b = DriverModel(node_id=1), DriverModel(node_id=2)
    a.step(0.001)
    assert a.sim_time != b.sim_time
    assert b.sim_time == 0.0
```

`tests/unit/test_layering.py`:

```python
"""driver 層が can / canopen に依存していないことを検証する。"""
import os
import re

DRIVER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "omsim",
    "driver",
)
FORBIDDEN = re.compile(r"^\s*(?:import|from)\s+(can|canopen)\b", re.MULTILINE)


def test_driver_layer_does_not_import_can_libraries():
    offenders = []
    for name in sorted(os.listdir(DRIVER_DIR)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(DRIVER_DIR, name)
        with open(path, encoding="utf-8") as handle:
            if FORBIDDEN.search(handle.read()):
                offenders.append(name)
    assert offenders == [], "driver 層が can/canopen を import している: {}".format(offenders)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_driver_model.py tests/unit/test_layering.py -v`
Expected: `test_driver_model.py` は FAIL（`No module named 'omsim.driver.model'`）、`test_layering.py` は PASS（まだ違反ファイルが無い）

- [ ] **Step 3: 最小の実装**

`omsim/driver/model.py`:

```python
"""BLVD-KRD ドライバの挙動モデル。can / canopen を import しないこと。"""
from omsim.driver.objects import ObjectRouter


class DriverModel(object):
    """1 台のドライバ。状態は全てインスタンス変数に持つ。"""

    router = ObjectRouter()

    DEVICE_NAME = "BLVD-KRD"

    def __init__(self, node_id):
        self.node_id = node_id
        self.sim_time = 0.0

    # --- 外向きの窓口は以下の 4 つだけ ---

    def read_object(self, index, sub=0):
        return self.router.read(self, index, sub)

    def write_object(self, index, sub=0, value=0):
        self.router.write(self, index, sub, value)

    def step(self, dt):
        self.sim_time += dt

    def snapshot(self):
        return {"node_id": self.node_id, "sim_time": self.sim_time}

    # --- オブジェクトハンドラ ---

    @router.reader(0x1008)
    def _read_device_name(self, sub):
        return self.DEVICE_NAME
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_driver_model.py tests/unit/test_layering.py -v`
Expected: 7 passed

- [ ] **Step 5: コミット**

```bash
git add omsim/driver/model.py tests/unit/test_driver_model.py tests/unit/test_layering.py
git commit -m "feat: DriverModel の窓口と driver 層の依存検証"
```

---

## Task 6: OD ブリッジ（LocalNode と DriverModel の接続）

**Files:**
- Create: `omsim/node/od_bridge.py`
- Test: `tests/unit/test_od_bridge.py`

**Interfaces:**
- Consumes: `load_eds`, `DriverModel`, `ObjectAccessError`
- Produces:
  - `build_local_node(node_id: int, od, model: DriverModel) -> canopen.LocalNode`
    `model` の `read_object` / `write_object` を `LocalNode` のコールバックに繋いだノードを返す
  - 変換規則: driver が `None` を返したら OD 既定値へフォールスルー、`ObjectAccessError` は `canopen.SdoAbortedError(abort_code)` に変換

`canopen` の read callback は `callback(index=..., subindex=..., od=obj)` で呼ばれ、`None` を返すと `data_store` → EDS の `value` → `default` の順にフォールスルーする。write callback は `callback(index=..., subindex=..., od=obj, data=bytes)` で呼ばれる。`data` は生バイト列なので `od.decode_raw(data)` で値に戻す。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_od_bridge.py`:

```python
import canopen
import pytest

from omsim.driver.errors import ABORT_VALUE_RANGE, ObjectAccessError
from omsim.driver.model import DriverModel
from omsim.node.eds import DEFAULT_EDS_PATH, load_eds
from omsim.node.od_bridge import build_local_node


@pytest.fixture
def od():
    return load_eds(DEFAULT_EDS_PATH)


def test_driver_value_wins_over_eds_default(od):
    node = build_local_node(1, od, DriverModel(node_id=1))
    assert node.get_data(0x1008, 0).rstrip(b"\x00").decode() == "BLVD-KRD"


def test_falls_through_to_eds_default_when_driver_returns_none(od):
    node = build_local_node(1, od, DriverModel(node_id=1))
    raw = node.get_data(0x414B, 0)
    assert od[0x414B].decode_raw(raw) == 1


def test_write_reaches_the_driver(od):
    class Spy(DriverModel):
        def __init__(self, node_id):
            DriverModel.__init__(self, node_id)
            self.seen = []

        def write_object(self, index, sub=0, value=0):
            self.seen.append((index, sub, value))

    model = Spy(node_id=1)
    node = build_local_node(1, od, model)
    node.set_data(0x414B, 0, od[0x414B].encode_raw(1))
    assert model.seen == [(0x414B, 0, 1)]


def test_object_access_error_becomes_sdo_abort(od):
    class Rejecting(DriverModel):
        def write_object(self, index, sub=0, value=0):
            raise ObjectAccessError(ABORT_VALUE_RANGE)

    node = build_local_node(1, od, Rejecting(node_id=1))
    with pytest.raises(canopen.SdoAbortedError) as exc:
        node.set_data(0x414B, 0, od[0x414B].encode_raw(1))
    assert exc.value.code == ABORT_VALUE_RANGE


def test_sdo_server_cob_ids_follow_node_id(od):
    node = build_local_node(5, od, DriverModel(node_id=5))
    assert node.sdo.rx_cobid == 0x605
    assert node.sdo.tx_cobid == 0x585
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_od_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.node.od_bridge'`

- [ ] **Step 3: 最小の実装**

`omsim/node/od_bridge.py`:

```python
"""canopen.LocalNode のコールバックを DriverModel に繋ぐ。"""
import canopen

from omsim.driver.errors import ObjectAccessError


def build_local_node(node_id, od, model):
    node = canopen.LocalNode(node_id, od)

    def on_read(index, subindex, od):
        try:
            return model.read_object(index, subindex)
        except ObjectAccessError as err:
            raise canopen.SdoAbortedError(err.abort_code)

    def on_write(index, subindex, od, data):
        try:
            model.write_object(index, subindex, od.decode_raw(data))
        except ObjectAccessError as err:
            raise canopen.SdoAbortedError(err.abort_code)

    node.add_read_callback(on_read)
    node.add_write_callback(on_write)
    node.driver_model = model
    return node
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_od_bridge.py -v`
Expected: 5 passed

`test_driver_value_wins_over_eds_default` が落ちる場合、`1008h` の EDS 上のデータ型が `VISIBLE_STRING` で `encode_raw` がパディングしない可能性がある。`node.get_data(0x1008, 0)` の実際のバイト列を確認し、期待値を実測に合わせる（`"BLVD-KRD"` が入っていることを確認できれば良い）。

- [ ] **Step 5: コミット**

```bash
git add omsim/node/od_bridge.py tests/unit/test_od_bridge.py
git commit -m "feat: LocalNode と DriverModel を繋ぐ OD ブリッジ"
```

---

## Task 7: CAN バスと NodeManager（複数ノードの同時実行）

**Files:**
- Create: `omsim/can/__init__.py`
- Create: `omsim/can/bus.py`
- Create: `omsim/sim/manager.py`
- Test: `tests/unit/test_manager.py`

**Interfaces:**
- Consumes: `SimClock`, `build_local_node`, `load_eds`, `DriverModel`
- Produces:
  - `open_network(channel: str = "vcan0", interface: str = "socketcan", bitrate: int = 500000) -> canopen.Network`
  - `close_network(network) -> None`
  - `NodeSpec(node_id: int, eds: str, mxex: Optional[str] = None)` — `collections.namedtuple`
  - `NodeManager(specs: List[NodeSpec], network=None, realtime: bool = True)`
  - `NodeManager.models: Dict[int, DriverModel]`
  - `NodeManager.nodes: Dict[int, canopen.LocalNode]`
  - `NodeManager.step() -> None` — 全ノードを 1 ステップ進める
  - `NodeManager.run_for(seconds: float) -> None`
  - `NodeManager.snapshot() -> Dict[str, Any]` — `{"sim_time": float, "nodes": {node_id: model.snapshot()}}`
  - `NodeManager.start() / stop()` — network への associate / 解除

`network=None` で作れることが重要（CAN 無しで NodeManager の単体テストができる）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_manager.py`:

```python
from omsim.node.eds import DEFAULT_EDS_PATH
from omsim.sim.manager import NodeManager, NodeSpec


def make_manager(*node_ids):
    specs = [NodeSpec(node_id=i, eds=DEFAULT_EDS_PATH, mxex=None) for i in node_ids]
    return NodeManager(specs, network=None, realtime=False)


def test_creates_one_model_and_node_per_spec():
    manager = make_manager(1, 2)
    assert sorted(manager.models) == [1, 2]
    assert sorted(manager.nodes) == [1, 2]
    assert manager.models[1] is not manager.models[2]


def test_node_count_is_not_fixed_to_two():
    manager = make_manager(1, 2, 3, 7)
    assert sorted(manager.models) == [1, 2, 3, 7]


def test_step_advances_every_node_by_one_millisecond():
    manager = make_manager(1, 2)
    manager.step()
    assert abs(manager.models[1].sim_time - 0.001) < 1e-12
    assert abs(manager.models[2].sim_time - 0.001) < 1e-12


def test_run_for_advances_all_nodes_together():
    manager = make_manager(1, 2)
    manager.run_for(0.5)
    for model in manager.models.values():
        assert abs(model.sim_time - 0.5) < 1e-9


def test_snapshot_contains_every_node():
    manager = make_manager(1, 2)
    manager.step()
    snap = manager.snapshot()
    assert abs(snap["sim_time"] - 0.001) < 1e-12
    assert sorted(snap["nodes"]) == [1, 2]
    assert snap["nodes"][2]["node_id"] == 2


def test_sdo_cob_ids_do_not_collide_between_nodes():
    manager = make_manager(1, 2)
    assert manager.nodes[1].sdo.rx_cobid != manager.nodes[2].sdo.rx_cobid
    assert manager.nodes[1].emcy.cob_id != manager.nodes[2].emcy.cob_id
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.sim.manager'`

- [ ] **Step 3: 最小の実装**

`omsim/can/__init__.py`: 空ファイル

`omsim/can/bus.py`:

```python
"""SocketCAN への接続。実機の can0 と vcan0 で同じコードが動く。"""
import canopen


def open_network(channel="vcan0", interface="socketcan", bitrate=500000):
    network = canopen.Network()
    network.connect(channel=channel, interface=interface, bitrate=bitrate)
    return network


def close_network(network):
    if network is not None:
        network.disconnect()
```

`omsim/sim/manager.py`:

```python
"""複数ノードを 1 プロセスで同時に進める。"""
import collections

from omsim.driver.model import DriverModel
from omsim.node.eds import load_eds
from omsim.node.od_bridge import build_local_node
from omsim.sim.clock import SimClock

NodeSpec = collections.namedtuple("NodeSpec", ["node_id", "eds", "mxex"])
NodeSpec.__new__.__defaults__ = (None,)


class NodeManager(object):
    def __init__(self, specs, network=None, realtime=True):
        self.clock = SimClock(realtime=realtime)
        self.network = network
        self.models = {}
        self.nodes = {}
        self._started = False
        for spec in specs:
            od = load_eds(spec.eds)
            model = DriverModel(node_id=spec.node_id)
            self.models[spec.node_id] = model
            self.nodes[spec.node_id] = build_local_node(spec.node_id, od, model)

    def start(self):
        if self.network is None or self._started:
            return
        for node in self.nodes.values():
            self.network[node.id] = node
        self._started = True

    def stop(self):
        if self.network is None or not self._started:
            return
        for node in self.nodes.values():
            node.remove_network()
        self._started = False

    def step(self):
        dt = self.clock.advance()
        for model in self.models.values():
            model.step(dt)

    def run_for(self, seconds):
        steps = int(round(seconds / SimClock.STEP_SECONDS))
        for _ in range(steps):
            self.step()

    def snapshot(self):
        return {
            "sim_time": self.clock.now,
            "nodes": dict(
                (node_id, model.snapshot()) for node_id, model in self.models.items()
            ),
        }
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_manager.py -v`
Expected: 6 passed

`self.network[node.id] = node` が `LocalNode` を受け付けない場合は `self.network.add_node(node)` に変える（`Network` は `MutableMapping` で `__setitem__` が `associate_network` を呼ぶ実装。実際の挙動を `python -c` で確認して合わせる）。

- [ ] **Step 5: コミット**

```bash
git add omsim/can/__init__.py omsim/can/bus.py omsim/sim/manager.py tests/unit/test_manager.py
git commit -m "feat: CAN バス接続と複数ノードを進める NodeManager"
```

---

## Task 8: vcan0 セットアップと vcan0 越しの SDO 結合テスト

**Files:**
- Create: `scripts/setup_vcan.sh`
- Create: `scripts/omsim-vcan.service`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`
- Test: `tests/integration/test_sdo_over_vcan.py`

**Interfaces:**
- Consumes: `open_network`, `close_network`, `NodeManager`, `NodeSpec`
- Produces:
  - `scripts/setup_vcan.sh <ifname>` — 冪等に vcan を作って up する
  - pytest fixture `vcan_available`（`tests/integration/conftest.py`）— `vcan0` が無い環境では skip し、あればインターフェース名を返す
  - pytest fixture `running_sim` — 2 ノードのシミュレータを別スレッドで実時間で走らせる（マスタから SDO を投げるテスト用）
  - pytest fixture `master` — 被試験体と同じ立場の `canopen.Network`
  - Task 19 で fixture `stepped_sim`（テスト側が明示的に step を進める、スレッドなし）を追加する

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/__init__.py`: 空ファイル

`tests/integration/conftest.py`:

```python
import subprocess
import threading

import pytest

from omsim.can.bus import close_network, open_network
from omsim.node.eds import DEFAULT_EDS_PATH
from omsim.sim.manager import NodeManager, NodeSpec

VCAN = "vcan0"


def _vcan_is_up():
    try:
        out = subprocess.check_output(["ip", "-o", "link", "show", VCAN])
    except (OSError, subprocess.CalledProcessError):
        return False
    return b"state UP" in out or b"UNKNOWN" in out


@pytest.fixture(scope="session")
def vcan_available():
    if not _vcan_is_up():
        pytest.skip("{} が無いので skip。scripts/setup_vcan.sh を実行してください".format(VCAN))
    return VCAN


@pytest.fixture
def running_sim(vcan_available):
    """node_id 1,2 のシミュレータを別スレッドで走らせる。"""
    network = open_network(channel=vcan_available)
    specs = [
        NodeSpec(node_id=1, eds=DEFAULT_EDS_PATH),
        NodeSpec(node_id=2, eds=DEFAULT_EDS_PATH),
    ]
    manager = NodeManager(specs, network=network, realtime=True)
    manager.start()
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            manager.step()

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    yield manager
    stop.set()
    thread.join(timeout=2.0)
    manager.stop()
    close_network(network)


@pytest.fixture
def master(vcan_available):
    """被試験体と同じ立場のマスタ。"""
    network = open_network(channel=vcan_available)
    yield network
    close_network(network)
```

`tests/integration/test_sdo_over_vcan.py`:

```python
import canopen
import pytest

from omsim.node.eds import DEFAULT_EDS_PATH

pytestmark = pytest.mark.vcan


def _remote(master, node_id):
    node = canopen.RemoteNode(node_id, DEFAULT_EDS_PATH)
    master.add_node(node)
    node.sdo.RESPONSE_TIMEOUT = 1.0
    return node


def test_reads_device_name_over_vcan(running_sim, master):
    node = _remote(master, 1)
    assert "BLVD-KRD" in node.sdo[0x1008].raw.rstrip("\x00")


def test_reads_manufacturer_parameter_default_over_vcan(running_sim, master):
    node = _remote(master, 1)
    assert node.sdo[0x414B].raw == 1


def test_aborts_on_unknown_index(running_sim, master):
    node = _remote(master, 1)
    with pytest.raises(canopen.SdoAbortedError) as exc:
        node.sdo.upload(0x5FFF, 0)
    assert exc.value.code == 0x06020000


def test_two_nodes_answer_independently(running_sim, master):
    one = _remote(master, 1)
    two = _remote(master, 2)
    assert one.sdo[0x414B].raw == 1
    assert two.sdo[0x414B].raw == 1
    assert one.sdo.rx_cobid != two.sdo.rx_cobid
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/integration -v`
Expected: `vcan0` が無ければ全て SKIP、あれば FAIL（`scripts/setup_vcan.sh` 未作成でも conftest は動く）。まず SKIP か FAIL のどちらになるかを確認する。

- [ ] **Step 3: vcan0 を作れるようにする**

`scripts/setup_vcan.sh`:

```bash
#!/bin/bash
# vcan インターフェースを冪等に作成して up する。要 sudo。
set -eu
IFACE="${1:-vcan0}"

sudo modprobe vcan
if ! ip link show "$IFACE" >/dev/null 2>&1; then
    sudo ip link add dev "$IFACE" type vcan
fi
sudo ip link set up "$IFACE"
ip -o link show "$IFACE"
```

`scripts/omsim-vcan.service`:

```ini
[Unit]
Description=omsim virtual CAN interface (vcan0)
After=network-pre.target
Before=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c '/usr/sbin/modprobe vcan && (/sbin/ip link show vcan0 || /sbin/ip link add dev vcan0 type vcan) && /sbin/ip link set up vcan0'

[Install]
WantedBy=multi-user.target
```

Run:

```bash
chmod +x scripts/setup_vcan.sh
./scripts/setup_vcan.sh vcan0
```

Expected: `vcan0: <NOARP,UP,LOWER_UP> ...` の行が出る

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/integration -v`
Expected: 4 passed

`test_reads_device_name_over_vcan` が型エラーで落ちる場合、`1008h` が `VISIBLE_STRING` なので `.raw` が `str` か `bytes` かを実測して合わせる。

- [ ] **Step 5: コミット**

```bash
git add scripts/setup_vcan.sh scripts/omsim-vcan.service tests/integration
git commit -m "feat: vcan0 セットアップと vcan 越しの SDO 結合テスト"
```

---

## Task 9: CANopen フレームのデコードと Recorder

**Files:**
- Create: `omsim/sim/decode.py`
- Create: `omsim/sim/recorder.py`
- Test: `tests/unit/test_decode.py`
- Test: `tests/unit/test_recorder.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `describe_frame(can_id: int, data: bytes, node_ids: Optional[Iterable[int]] = None) -> str`
    例: `"SDO wr node1 6040h:00 = 000Fh"` / `"TPDO1 node1 len=8"` / `"NMT start node1"` / `"HB node1 OPERATIONAL"` / `"EMCY node1 code=7305h"`
  - `Recorder(path: Optional[str])`
    `.frame(direction: str, can_id: int, data: bytes, sim_time: float) -> None`
    `.state(snapshot: Dict[str, Any]) -> None`
    `.close() -> None`
    `.recent_frames(limit: int = 100) -> List[Dict[str, Any]]` — Web とテスト用のリングバッファ
  - `attach_recorder(network, recorder, clock) -> FrameListener` — バスを流れる全フレームを Recorder に流す
  - jsonl の 1 行は `{"t": float, "kind": "frame"|"state", ...}`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_decode.py`:

```python
from omsim.sim.decode import describe_frame


def test_decodes_nmt_start():
    assert describe_frame(0x000, bytes([0x01, 0x01])) == "NMT start node1"


def test_decodes_nmt_reset_node():
    assert describe_frame(0x000, bytes([0x81, 0x02])) == "NMT reset-node node2"


def test_decodes_sdo_expedited_download_request():
    data = bytes([0x2B, 0x40, 0x60, 0x00, 0x0F, 0x00, 0x00, 0x00])
    assert describe_frame(0x601, data) == "SDO wr node1 6040h:00 = 000Fh"


def test_decodes_sdo_upload_request():
    data = bytes([0x40, 0x41, 0x60, 0x00, 0x00, 0x00, 0x00, 0x00])
    assert describe_frame(0x601, data) == "SDO rd node1 6041h:00"


def test_decodes_sdo_abort():
    data = bytes([0x80, 0x40, 0x60, 0x00, 0x00, 0x00, 0x02, 0x06])
    assert describe_frame(0x581, data) == "SDO abort node1 6040h:00 code=06020000h"


def test_decodes_heartbeat():
    assert describe_frame(0x701, bytes([0x05])) == "HB node1 OPERATIONAL"


def test_decodes_emcy():
    data = bytes([0x05, 0x73, 0x21, 0x00, 0x00, 0x00, 0x00, 0x00])
    assert describe_frame(0x081, data) == "EMCY node1 code=7305h reg=21h"


def test_decodes_tpdo():
    assert describe_frame(0x181, bytes(range(8))) == "TPDO1 node1 len=8"


def test_decodes_rpdo():
    assert describe_frame(0x201, bytes(range(4))) == "RPDO1 node1 len=4"


def test_decodes_sync():
    assert describe_frame(0x080, b"") == "SYNC"


def test_unknown_id_is_reported_as_raw():
    assert describe_frame(0x123, bytes([0xAA])) == "raw 123h len=1"
```

`tests/unit/test_recorder.py`:

```python
import json
import os

from omsim.sim.recorder import Recorder


def test_writes_frames_and_state_as_jsonl(tmp_path):
    path = os.path.join(str(tmp_path), "run.jsonl")
    rec = Recorder(path)
    rec.frame("rx", 0x601, bytes([0x40, 0x41, 0x60, 0x00, 0, 0, 0, 0]), 0.001)
    rec.state({"sim_time": 0.001, "nodes": {1: {"node_id": 1}}})
    rec.close()

    lines = [json.loads(line) for line in open(path, encoding="utf-8")]
    assert lines[0]["kind"] == "frame"
    assert lines[0]["can_id"] == 0x601
    assert lines[0]["text"] == "SDO rd node1 6041h:00"
    assert lines[1]["kind"] == "state"


def test_keeps_recent_frames_in_memory_without_a_path():
    rec = Recorder(None)
    for i in range(5):
        rec.frame("tx", 0x181, bytes([i]), 0.001 * i)
    recent = rec.recent_frames(limit=3)
    assert len(recent) == 3
    assert recent[-1]["can_id"] == 0x181
    rec.close()


def test_ring_buffer_is_bounded():
    rec = Recorder(None, buffer_size=10)
    for i in range(50):
        rec.frame("tx", 0x181, bytes([1]), 0.0)
    assert len(rec.recent_frames(limit=100)) == 10
    rec.close()
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_decode.py tests/unit/test_recorder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.sim.decode'`

- [ ] **Step 3: 最小の実装**

`omsim/sim/decode.py`:

```python
"""CAN フレームを人間が読める 1 行に変換する。HP-5143E 3.3 (COB-ID) と 4 章に対応。"""
import struct

NMT_COMMANDS = {
    0x01: "start",
    0x02: "stop",
    0x80: "pre-operational",
    0x81: "reset-node",
    0x82: "reset-communication",
}
NMT_STATES = {0x00: "BOOTUP", 0x04: "STOPPED", 0x05: "OPERATIONAL", 0x7F: "PRE-OPERATIONAL"}
TPDO_BASES = (0x180, 0x280, 0x380, 0x480)
RPDO_BASES = (0x200, 0x300, 0x400, 0x500)


def _index_sub(data):
    index = data[1] | (data[2] << 8)
    return index, data[3]


def _sdo_request(node_id, data):
    ccs = data[0] >> 5
    index, sub = _index_sub(data)
    if ccs == 2:  # upload
        return "SDO rd node{} {:04X}h:{:02X}".format(node_id, index, sub)
    if ccs == 1:  # download
        value = struct.unpack("<I", data[4:8])[0]
        return "SDO wr node{} {:04X}h:{:02X} = {:04X}h".format(node_id, index, sub, value)
    if data[0] == 0x80:
        code = struct.unpack("<I", data[4:8])[0]
        return "SDO abort node{} {:04X}h:{:02X} code={:08X}h".format(node_id, index, sub, code)
    return "SDO node{} cmd={:02X}h".format(node_id, data[0])


def _sdo_response(node_id, data):
    if data[0] == 0x80:
        index, sub = _index_sub(data)
        code = struct.unpack("<I", data[4:8])[0]
        return "SDO abort node{} {:04X}h:{:02X} code={:08X}h".format(node_id, index, sub, code)
    scs = data[0] >> 5
    index, sub = _index_sub(data)
    if scs == 2:  # upload response
        value = struct.unpack("<I", data[4:8])[0]
        return "SDO rd-resp node{} {:04X}h:{:02X} = {:04X}h".format(node_id, index, sub, value)
    if scs == 3:  # download response
        return "SDO wr-ack node{} {:04X}h:{:02X}".format(node_id, index, sub)
    return "SDO node{} resp={:02X}h".format(node_id, data[0])


def describe_frame(can_id, data, node_ids=None):
    data = bytes(data)
    if can_id == 0x000 and len(data) >= 2:
        return "NMT {} node{}".format(NMT_COMMANDS.get(data[0], "cmd{:02X}h".format(data[0])), data[1])
    if can_id == 0x080 and not data:
        return "SYNC"
    if 0x081 <= can_id <= 0x0FF and len(data) >= 3:
        code = data[0] | (data[1] << 8)
        return "EMCY node{} code={:04X}h reg={:02X}h".format(can_id - 0x080, code, data[2])
    if 0x701 <= can_id <= 0x77F and len(data) >= 1:
        state = NMT_STATES.get(data[0], "{:02X}h".format(data[0]))
        return "HB node{} {}".format(can_id - 0x700, state)
    if 0x581 <= can_id <= 0x5FF and len(data) == 8:
        return _sdo_response(can_id - 0x580, data)
    if 0x601 <= can_id <= 0x67F and len(data) == 8:
        return _sdo_request(can_id - 0x600, data)
    for number, base in enumerate(TPDO_BASES, start=1):
        if base + 1 <= can_id <= base + 0x7F:
            return "TPDO{} node{} len={}".format(number, can_id - base, len(data))
    for number, base in enumerate(RPDO_BASES, start=1):
        if base + 1 <= can_id <= base + 0x7F:
            return "RPDO{} node{} len={}".format(number, can_id - base, len(data))
    return "raw {:X}h len={}".format(can_id, len(data))
```

`omsim/sim/recorder.py`:

```python
"""CAN フレームと状態スナップショットを jsonl に記録する。"""
import collections
import json

from omsim.sim.decode import describe_frame


class Recorder(object):
    def __init__(self, path, buffer_size=2000):
        self._handle = open(path, "w", encoding="utf-8") if path else None
        self._buffer = collections.deque(maxlen=buffer_size)

    def frame(self, direction, can_id, data, sim_time):
        record = {
            "kind": "frame",
            "t": sim_time,
            "dir": direction,
            "can_id": can_id,
            "data": bytes(data).hex(),
            "text": describe_frame(can_id, data),
        }
        self._buffer.append(record)
        self._write(record)

    def state(self, snapshot):
        record = {"kind": "state", "t": snapshot.get("sim_time", 0.0), "snapshot": snapshot}
        self._write(record)

    def recent_frames(self, limit=100):
        items = list(self._buffer)
        return items[-limit:]

    def close(self):
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def _write(self, record):
        if self._handle is not None:
            self._handle.write(json.dumps(record, default=str) + "\n")
            self._handle.flush()
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_decode.py tests/unit/test_recorder.py -v`
Expected: 14 passed

- [ ] **Step 5: コミット**

```bash
git add omsim/sim/decode.py omsim/sim/recorder.py tests/unit/test_decode.py tests/unit/test_recorder.py
git commit -m "feat: CANopen フレームデコードと jsonl Recorder"
```

- [ ] **Step 6: バスに繋ぐ部分の失敗するテストを書く**

`tests/unit/test_recorder_attach.py`:

```python
from omsim.sim.clock import SimClock
from omsim.sim.recorder import Recorder, attach_recorder


class FakeMessage(object):
    def __init__(self, arbitration_id, data):
        self.arbitration_id = arbitration_id
        self.data = data
        self.is_error_frame = False


class FakeNetwork(object):
    def __init__(self):
        self.listeners = []


def test_attaches_a_listener_to_the_network():
    network = FakeNetwork()
    recorder = Recorder(None)
    attach_recorder(network, recorder, SimClock(realtime=False))
    assert len(network.listeners) == 1
    recorder.close()


def test_received_frames_land_in_the_recorder():
    network = FakeNetwork()
    recorder = Recorder(None)
    attach_recorder(network, recorder, SimClock(realtime=False))
    listener = network.listeners[0]
    listener.on_message_received(
        FakeMessage(0x601, bytes([0x40, 0x41, 0x60, 0x00, 0, 0, 0, 0]))
    )
    frames = recorder.recent_frames()
    assert len(frames) == 1
    assert frames[0]["can_id"] == 0x601
    assert frames[0]["text"] == "SDO rd node1 6041h:00"
    recorder.close()


def test_frame_timestamp_comes_from_the_sim_clock():
    network = FakeNetwork()
    recorder = Recorder(None)
    clock = SimClock(realtime=False)
    attach_recorder(network, recorder, clock)
    clock.advance_for(0.5)
    network.listeners[0].on_message_received(FakeMessage(0x181, bytes([1])))
    assert abs(recorder.recent_frames()[0]["t"] - 0.5) < 1e-9
    recorder.close()


def test_error_frames_are_ignored():
    network = FakeNetwork()
    recorder = Recorder(None)
    attach_recorder(network, recorder, SimClock(realtime=False))
    message = FakeMessage(0x601, bytes(8))
    message.is_error_frame = True
    network.listeners[0].on_message_received(message)
    assert recorder.recent_frames() == []
    recorder.close()
```

- [ ] **Step 7: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_recorder_attach.py -v`
Expected: FAIL — `ImportError: cannot import name 'attach_recorder'`

- [ ] **Step 8: `omsim/sim/recorder.py` に追記**

```python
class FrameListener(object):
    """python-can の Listener。canopen.Network.listeners に載せる。"""

    def __init__(self, recorder, clock):
        self._recorder = recorder
        self._clock = clock

    def on_message_received(self, msg):
        if getattr(msg, "is_error_frame", False):
            return
        self._recorder.frame("bus", msg.arbitration_id, bytes(msg.data), self._clock.now)

    def on_error(self, exc):
        pass

    def stop(self):
        pass


def attach_recorder(network, recorder, clock):
    listener = FrameListener(recorder, clock)
    network.listeners.append(listener)
    notifier = getattr(network, "notifier", None)
    if notifier is not None:
        # python-can 4.5.0 の Notifier は __init__ で listeners のコピーを取るため、
        # connect() 後に network.listeners へ append しただけでは効かない。
        notifier.add_listener(listener)
    return listener
```

`from omsim.sim.decode import describe_frame` の下に置く。この形なら `open_network()` の前でも後でも動く。

- [ ] **Step 9: テストが通ることを確認してコミット**

Run: `python -m pytest tests/unit/test_recorder_attach.py -v`
Expected: 4 passed

```bash
git add omsim/sim/recorder.py tests/unit/test_recorder_attach.py
git commit -m "feat: CAN フレームを Recorder に流す listener"
```

---

## Task 10: 本体 CLI（omsim）

**Files:**
- Create: `omsim/apps/__init__.py`
- Create: `omsim/apps/omsim_main.py`
- Test: `tests/unit/test_omsim_cli.py`

**Interfaces:**
- Consumes: `NodeManager`, `NodeSpec`, `open_network`, `close_network`, `Recorder`, `find_eds`
- Produces:
  - `parse_args(argv: List[str]) -> argparse.Namespace` — 属性 `nodes` (List[NodeSpec]), `channel`, `interface`, `bitrate`, `eds`, `record`, `duration`
  - `main(argv: Optional[List[str]] = None) -> int`
  - CLI 形式: `omsim --channel vcan0 --eds BLVD-KRD_CANopen_V400.eds --node 1 --node 2=右モーター.mxex --record run.jsonl`
  - `--node` は `<id>` または `<id>=<mxex>`。複数指定可。省略時は `--node 1` 相当

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_omsim_cli.py`:

```python
import pytest

from omsim.apps.omsim_main import parse_args


def test_defaults_to_one_node_on_vcan0():
    args = parse_args([])
    assert args.channel == "vcan0"
    assert args.interface == "socketcan"
    assert args.bitrate == 500000
    assert [spec.node_id for spec in args.nodes] == [1]
    assert args.nodes[0].mxex is None


def test_parses_multiple_nodes():
    args = parse_args(["--node", "1", "--node", "2"])
    assert [spec.node_id for spec in args.nodes] == [1, 2]


def test_parses_node_with_mxex():
    args = parse_args(["--node", "2=/tmp/left.mxex"])
    assert args.nodes[0].node_id == 2
    assert args.nodes[0].mxex == "/tmp/left.mxex"


def test_every_node_gets_the_selected_eds():
    args = parse_args(["--eds", "BLVD-KRD_CANopen_V400.eds", "--node", "1", "--node", "2"])
    assert args.nodes[0].eds.endswith("BLVD-KRD_CANopen_V400.eds")
    assert args.nodes[1].eds == args.nodes[0].eds


def test_rejects_duplicate_node_ids():
    with pytest.raises(SystemExit):
        parse_args(["--node", "1", "--node", "1"])


def test_rejects_non_numeric_node_id():
    with pytest.raises(SystemExit):
        parse_args(["--node", "abc"])
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_omsim_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.apps'`

- [ ] **Step 3: 最小の実装**

`omsim/apps/__init__.py`: 空ファイル

`omsim/apps/omsim_main.py`:

```python
"""omsim 本体の CLI。"""
import argparse
import signal
import sys

from omsim.can.bus import close_network, open_network
from omsim.node.eds import DEFAULT_EDS_PATH, find_eds
from omsim.sim.manager import NodeManager, NodeSpec
from omsim.sim.recorder import Recorder, attach_recorder


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="omsim", description="BLVD-KRD CANopen シミュレータ")
    parser.add_argument("--channel", default="vcan0")
    parser.add_argument("--interface", default="socketcan")
    parser.add_argument("--bitrate", type=int, default=500000)
    parser.add_argument("--eds", default=DEFAULT_EDS_PATH)
    parser.add_argument(
        "--node",
        action="append",
        dest="node_specs",
        metavar="ID[=MXEX]",
        help="ノードを追加する。複数指定可。例: --node 1 --node 2=left.mxex",
    )
    parser.add_argument("--record", default=None, help="jsonl の記録先")
    parser.add_argument("--duration", type=float, default=None, help="指定秒で終了（テスト用）")
    args = parser.parse_args(argv)

    eds_path = find_eds(args.eds)
    raw_specs = args.node_specs or ["1"]
    nodes = []
    seen = set()
    for item in raw_specs:
        if "=" in item:
            id_part, mxex = item.split("=", 1)
        else:
            id_part, mxex = item, None
        if not id_part.strip().isdigit():
            parser.error("--node の ID が数値ではありません: {}".format(item))
        node_id = int(id_part)
        if node_id in seen:
            parser.error("--node の ID が重複しています: {}".format(node_id))
        seen.add(node_id)
        nodes.append(NodeSpec(node_id=node_id, eds=eds_path, mxex=mxex))
    args.nodes = nodes
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    recorder = Recorder(args.record)
    network = open_network(args.channel, args.interface, args.bitrate)
    manager = NodeManager(args.nodes, network=network, realtime=True)
    attach_recorder(network, recorder, manager.clock)
    manager.start()

    stopping = {"flag": False}

    def on_signal(signum, frame):
        stopping["flag"] = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    print("omsim: {} on {} nodes={}".format(
        args.interface, args.channel, sorted(manager.models)))
    try:
        while not stopping["flag"]:
            manager.step()
            if manager.clock.tick_count % 100 == 0:
                recorder.state(manager.snapshot())
            if args.duration is not None and manager.clock.now >= args.duration:
                break
    finally:
        manager.stop()
        close_network(network)
        recorder.close()
    return 0
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_omsim_cli.py -v`
Expected: 6 passed

vcan0 がある環境で実際に起動できることも確認する:

Run: `python -m omsim.apps.omsim_main --node 1 --node 2 --duration 0.5`
Expected: `omsim: socketcan on vcan0 nodes=[1, 2]` が出て 0.5 秒後に終了、終了コード 0

- [ ] **Step 5: コミット**

```bash
git add omsim/apps/__init__.py omsim/apps/omsim_main.py tests/unit/test_omsim_cli.py
git commit -m "feat: omsim 本体 CLI（複数ノード指定）"
```

---

## Task 11: シナリオランナー最小版

**Files:**
- Create: `omsim/apps/scenario.py`
- Create: `tests/scenarios/sdo_smoke.yaml`
- Test: `tests/unit/test_scenario_parse.py`
- Test: `tests/integration/test_scenario_run.py`

**Interfaces:**
- Consumes: `open_network`, `close_network`
- Produces:
  - `load_scenario(path: str) -> Scenario` — `Scenario` は `collections.namedtuple("Scenario", ["name", "nodes", "steps"])`
  - `StepResult = collections.namedtuple("StepResult", ["index", "kind", "ok", "detail"])`
  - `run_scenario(scenario: Scenario, network, timeout_default: float = 2.0, eds: Optional[str] = None) -> List[StepResult]`
  - `write_junit(results: List[StepResult], scenario: Scenario, path: str) -> None`
  - `main(argv: Optional[List[str]] = None) -> int` — 全 step 成功で 0、1 つでも失敗で 1
  - 対応ステップ（設計書 8 節の 6 種）: `nmt`, `sdo_write`, `sdo_read`, `expect`, `wait`, `pdo_send`

- [ ] **Step 1: 失敗するテストを書く**

`tests/scenarios/sdo_smoke.yaml`:

```yaml
name: SDO で装置名とパラメータ既定値が読める
nodes: [1, 2]
steps:
  - nmt: start
  - sdo_read: {index: 0x1008}
  - expect: {index: 0x414B, value: 1}
  - wait: {seconds: 0.05}
  - expect: {node: 2, index: 0x4186, value: 3000}
```

`tests/unit/test_scenario_parse.py`:

```python
import os

from omsim.apps.scenario import load_scenario

SCENARIO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scenarios",
    "sdo_smoke.yaml",
)


def test_parses_name_and_nodes():
    scenario = load_scenario(SCENARIO)
    assert scenario.name.startswith("SDO で")
    assert scenario.nodes == [1, 2]


def test_parses_every_step_in_order():
    scenario = load_scenario(SCENARIO)
    assert [step["kind"] for step in scenario.steps] == [
        "nmt",
        "sdo_read",
        "expect",
        "wait",
        "expect",
    ]


def test_step_without_node_targets_all_nodes():
    scenario = load_scenario(SCENARIO)
    expect_all = scenario.steps[2]
    assert expect_all["nodes"] == [1, 2]


def test_step_with_explicit_node_targets_only_that_node():
    scenario = load_scenario(SCENARIO)
    assert scenario.steps[4]["nodes"] == [2]


def test_hex_indices_are_parsed_as_integers():
    scenario = load_scenario(SCENARIO)
    assert scenario.steps[1]["index"] == 0x1008
    assert scenario.steps[2]["index"] == 0x414B
```

`tests/integration/test_scenario_run.py`:

```python
import os

import pytest

from omsim.apps.scenario import load_scenario, run_scenario, write_junit

pytestmark = pytest.mark.vcan

SCENARIO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scenarios",
    "sdo_smoke.yaml",
)


def test_smoke_scenario_all_steps_pass(running_sim, master, tmp_path):
    scenario = load_scenario(SCENARIO)
    results = run_scenario(scenario, master)
    failed = [r for r in results if not r.ok]
    assert failed == [], "失敗したステップ: {}".format(failed)


def test_junit_xml_is_written(running_sim, master, tmp_path):
    scenario = load_scenario(SCENARIO)
    results = run_scenario(scenario, master)
    path = os.path.join(str(tmp_path), "junit.xml")
    write_junit(results, scenario, path)
    xml = open(path, encoding="utf-8").read()
    assert "<testsuite" in xml
    assert 'tests="{}"'.format(len(results)) in xml


def test_wrong_expectation_is_reported_as_failure(running_sim, master):
    scenario = load_scenario(SCENARIO)._replace(
        steps=[{"kind": "expect", "nodes": [1], "index": 0x414B, "value": 999, "timeout": 0.2}]
    )
    results = run_scenario(scenario, master)
    assert results[0].ok is False
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_scenario_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.apps.scenario'`

- [ ] **Step 3: 最小の実装**

`omsim/apps/scenario.py`:

```python
"""YAML シナリオをマスタ役として流す最小版ランナー。"""
import argparse
import collections
import sys
import time
import xml.etree.ElementTree as ET

import canopen
import yaml

from omsim.can.bus import close_network, open_network
from omsim.node.eds import DEFAULT_EDS_PATH, find_eds

Scenario = collections.namedtuple("Scenario", ["name", "nodes", "steps"])
StepResult = collections.namedtuple("StepResult", ["index", "kind", "ok", "detail"])

STEP_KINDS = ("nmt", "sdo_write", "sdo_read", "expect", "wait", "pdo_send")
NMT_COMMANDS = {
    "start": 0x01,
    "stop": 0x02,
    "pre-operational": 0x80,
    "reset": 0x81,
    "reset-comm": 0x82,
}


def _as_int(value):
    if isinstance(value, str):
        return int(value, 0)
    return value


def load_scenario(path):
    with open(path, encoding="utf-8") as handle:
        doc = yaml.safe_load(handle)
    nodes = [int(n) for n in doc.get("nodes", [1])]
    steps = []
    for raw in doc["steps"]:
        kind = next(k for k in raw if k in STEP_KINDS)
        body = raw[kind]
        step = {"kind": kind}
        if isinstance(body, dict):
            step.update(body)
        else:
            step["value"] = body
        for key in ("index", "sub", "value", "mask"):
            if key in step:
                step[key] = _as_int(step[key])
        step.setdefault("sub", 0)
        step["nodes"] = [int(step.pop("node"))] if "node" in step else list(nodes)
        steps.append(step)
    return Scenario(name=doc["name"], nodes=nodes, steps=steps)


def _remote_nodes(network, node_ids, eds):
    remotes = {}
    for node_id in node_ids:
        node = canopen.RemoteNode(node_id, eds)
        network.add_node(node)
        node.sdo.RESPONSE_TIMEOUT = 1.0
        remotes[node_id] = node
    return remotes


def _matches(actual, step):
    if "mask" in step:
        return (actual & step["mask"]) == step["value"]
    tolerance = step.get("tolerance", 0)
    return abs(actual - step["value"]) <= tolerance


def _run_expect(remote, step, timeout):
    deadline = time.monotonic() + timeout
    actual = None
    while time.monotonic() < deadline:
        actual = remote.sdo.upload(step["index"], step["sub"])
        actual = int.from_bytes(actual, "little", signed=False)
        if _matches(actual, step):
            return True, "actual={}".format(actual)
        time.sleep(0.01)
    return False, "actual={} expected={}".format(actual, step["value"])


def run_scenario(scenario, network, timeout_default=2.0, eds=None):
    remotes = _remote_nodes(network, scenario.nodes, find_eds(eds or DEFAULT_EDS_PATH))
    results = []
    for position, step in enumerate(scenario.steps):
        kind = step["kind"]
        ok, detail = True, ""
        try:
            for node_id in step["nodes"]:
                remote = remotes[node_id]
                if kind == "nmt":
                    code = NMT_COMMANDS[step["value"]]
                    network.send_message(0x000, bytes([code, node_id]))
                elif kind == "wait":
                    time.sleep(float(step.get("seconds", 0.0)))
                    break
                elif kind == "sdo_write":
                    remote.sdo.download(
                        step["index"], step["sub"],
                        int(step["value"]).to_bytes(
                            len(remote.object_dictionary[step["index"]]) // 8, "little"),
                    )
                elif kind == "sdo_read":
                    remote.sdo.upload(step["index"], step["sub"])
                elif kind == "expect":
                    ok, detail = _run_expect(
                        remote, step, float(step.get("timeout", timeout_default)))
                    if not ok:
                        break
                elif kind == "pdo_send":
                    network.send_message(_as_int(step["cob_id"]), bytes(step["data"]))
                else:
                    raise NotImplementedError("未対応のステップ: {}".format(kind))
        except Exception as err:  # シナリオ実行の失敗は結果として記録する
            ok, detail = False, "{}: {}".format(type(err).__name__, err)
        results.append(StepResult(index=position, kind=kind, ok=ok, detail=detail))
    return results


def write_junit(results, scenario, path):
    failures = sum(0 if r.ok else 1 for r in results)
    suite = ET.Element(
        "testsuite",
        name=scenario.name,
        tests=str(len(results)),
        failures=str(failures),
        errors="0",
    )
    for result in results:
        case = ET.SubElement(
            suite, "testcase",
            classname=scenario.name,
            name="step{}-{}".format(result.index, result.kind),
        )
        if not result.ok:
            failure = ET.SubElement(case, "failure", message=result.detail or "failed")
            failure.text = result.detail
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="omsim-scenario")
    parser.add_argument("scenario")
    parser.add_argument("--channel", default="vcan0")
    parser.add_argument("--interface", default="socketcan")
    parser.add_argument("--bitrate", type=int, default=500000)
    parser.add_argument("--eds", default=DEFAULT_EDS_PATH)
    parser.add_argument("--junit", default=None)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    scenario = load_scenario(args.scenario)
    network = open_network(args.channel, args.interface, args.bitrate)
    try:
        results = run_scenario(scenario, network, eds=args.eds)
    finally:
        close_network(network)
    if args.junit:
        write_junit(results, scenario, args.junit)
    for result in results:
        mark = "PASS" if result.ok else "FAIL"
        print("{} step{} {} {}".format(mark, result.index, result.kind, result.detail))
    return 0 if all(r.ok for r in results) else 1
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_scenario_parse.py tests/integration/test_scenario_run.py -v`
Expected: 8 passed（vcan0 が無い環境では integration の 3 件が SKIP）

- [ ] **Step 5: コミット**

```bash
git add omsim/apps/scenario.py tests/scenarios/sdo_smoke.yaml tests/unit/test_scenario_parse.py tests/integration/test_scenario_run.py
git commit -m "feat: シナリオランナー最小版と junit.xml 出力"
```

---

## Task 12: Vagrant への配置と手順書

**Files:**
- Create: `README.md`
- Create: `scripts/vagrant_provision.sh`
- Modify: `c:\Users\ktake\code\pitakuru_ws\src\Vagrantfile:10-11`
- Test: 手動確認（このタスクのみ自動テストなし。確認コマンドと期待出力を明記する）

**Interfaces:**
- Consumes: `scripts/setup_vcan.sh`
- Produces: VM 内 `/home/vagrant/KEISUU/omsim` に本リポジトリがマウントされ、`omsim` と `omsim-scenario` が VM の PATH で動く状態

- [ ] **Step 1: Vagrantfile に synced_folder を追加**

`c:\Users\ktake\code\pitakuru_ws\src\Vagrantfile` の 10-11 行目の直後に追加する。

追加前:

```ruby
    config.vm.synced_folder ".", "/home/vagrant/KEISUU/develop/src",
        owner: "vagrant", group: "vagrant"
```

追加後:

```ruby
    config.vm.synced_folder ".", "/home/vagrant/KEISUU/develop/src",
        owner: "vagrant", group: "vagrant"

    # オリエンタルモーター CAN シミュレータ
    config.vm.synced_folder "../../keisuu/oriental_motor_simulator", "/home/vagrant/KEISUU/omsim",
        owner: "vagrant", group: "vagrant"
```

- [ ] **Step 2: プロビジョニングスクリプトを書く**

`scripts/vagrant_provision.sh`:

```bash
#!/bin/bash
# Vagrant VM (Ubuntu 20.04 / Python 3.8) に omsim をセットアップする。
set -eu
REPO="${1:-/home/vagrant/KEISUU/omsim}"

sudo apt-get update
sudo apt-get install -y python3-pip can-utils

python3 -m pip install --user -r "$REPO/requirements.txt"
python3 -m pip install --user -e "$REPO"

sudo install -m 0644 "$REPO/scripts/omsim-vcan.service" /etc/systemd/system/omsim-vcan.service
sudo systemctl daemon-reload
sudo systemctl enable --now omsim-vcan.service

ip -o link show vcan0
python3 -c "import omsim; print('omsim', omsim.__version__)"
```

- [ ] **Step 3: VM 上で実際に走らせる**

Run（Windows 側 PowerShell、`pitakuru_ws/src` で）:

```bash
vagrant reload
vagrant ssh -c "bash /home/vagrant/KEISUU/omsim/scripts/vagrant_provision.sh"
```

Expected:
- `vcan0: <NOARP,UP,LOWER_UP> mtu 72 ...` の行が出る
- `omsim 0.1.0` が出る

共有フォルダが自動マウントされない場合（過去にこの VM で発生している）:

```bash
vagrant ssh -c "sudo mkdir -p /home/vagrant/KEISUU/omsim && sudo mount -t vboxsf -o uid=1000,gid=1000 oriental_motor_simulator /home/vagrant/KEISUU/omsim"
```

- [ ] **Step 4: VM 上でテストを全部通す**

Run:

```bash
vagrant ssh -c "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -v"
```

Expected: すべて passed（SKIP が 0 件であること。`vcan0` が上がっているので integration も走る）

- [ ] **Step 5: README を書いてコミット**

`README.md`:

```markdown
# オリエンタルモーター BLVD-KRD CANopen シミュレータ

実機のモーター・ドライバなしに、BLVD-KRD ドライバの CANopen 通信を PC 上で再現します。
複数台（右/左モーター）を 1 本の CAN バス上で同時にシミュレートできます。

- 設計書: `docs/superpowers/specs/2026-08-08-oriental-motor-simulator-design.md`
- 仕様の正本: `docs/oriental_motor/HP-5143E.pdf`（CANopen）、`docs/oriental_motor/HP-5141J.pdf`（機能編）

## セットアップ（Vagrant VM）

```bash
cd /home/vagrant/KEISUU/omsim
bash scripts/vagrant_provision.sh
```

## 起動

```bash
omsim --channel vcan0 --node 1 --node 2
```

## テスト

```bash
python3 -m pytest -v
```

## シナリオ実行

```bash
omsim-scenario tests/scenarios/sdo_smoke.yaml --junit junit.xml
```
```

```bash
git add README.md scripts/vagrant_provision.sh
git commit -m "docs: Vagrant への配置手順と README"
```

`pitakuru_ws` 側は別リポジトリなので、そちらでもコミットする:

```bash
cd /c/Users/ktake/code/pitakuru_ws/src
git add Vagrantfile
git commit -m "chore: oriental_motor_simulator を VM にマウント"
```

---

ここまでで P0 完了。**成果: vcan0 上で 2 ノードが SDO に応答し、シナリオを YAML で書いて junit.xml が出る。**

---

## Task 13: Cia402StateMachine の状態と Statusword

**Files:**
- Create: `omsim/driver/state_machine.py`
- Test: `tests/unit/test_state_machine.py`

**Interfaces:**
- Consumes: `ObjectAccessError`
- Produces:
  - `State` — 文字列定数クラス: `NOT_READY`, `SWITCH_ON_DISABLED`, `READY_TO_SWITCH_ON`, `SWITCHED_ON`, `OPERATION_ENABLED`, `QUICK_STOP_ACTIVE`, `FAULT_REACTION_ACTIVE`, `FAULT`
  - `Cia402StateMachine()`
  - `.state: str`
  - `.statusword: int`
  - `.controlword: int` — 最後に書かれた Controlword（読み出し用）
  - `.write_controlword(value: int) -> None`
  - `.step(dt: float) -> None`
  - `.set_fault(active: bool) -> None`
  - `.target_reached: bool`（読み書き。bit10 に反映）
  - `.internal_limit_active: bool`（bit11）
  - `.voltage_enabled: bool`（bit4、既定 True）
  - `.warning: bool`（bit7）
  - `.is_operation_enabled: bool`

Statusword のビット割り当てと状態コードは `docs/oriental_motor/HP-5143E.pdf` 6.1（p34）、遷移は 6.2（p35）。実装時に必ず該当ページを開いて突き合わせ、ページ番号をコメントに残す。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_state_machine.py`:

```python
from omsim.driver.state_machine import Cia402StateMachine, State

SHUTDOWN = 0x0006
SWITCH_ON = 0x0007
ENABLE_OPERATION = 0x000F
DISABLE_VOLTAGE = 0x0000
QUICK_STOP = 0x0002
FAULT_RESET = 0x0080


def enabled_machine():
    sm = Cia402StateMachine()
    sm.write_controlword(SHUTDOWN)
    sm.write_controlword(SWITCH_ON)
    sm.write_controlword(ENABLE_OPERATION)
    return sm


def test_starts_in_switch_on_disabled_after_first_step():
    sm = Cia402StateMachine()
    sm.step(0.001)
    assert sm.state == State.SWITCH_ON_DISABLED
    assert sm.statusword & 0x4F == 0x40


def test_shutdown_moves_to_ready_to_switch_on():
    sm = Cia402StateMachine()
    sm.write_controlword(SHUTDOWN)
    assert sm.state == State.READY_TO_SWITCH_ON
    assert sm.statusword & 0x6F == 0x21


def test_switch_on_moves_to_switched_on():
    sm = Cia402StateMachine()
    sm.write_controlword(SHUTDOWN)
    sm.write_controlword(SWITCH_ON)
    assert sm.state == State.SWITCHED_ON
    assert sm.statusword & 0x6F == 0x23


def test_enable_operation_moves_to_operation_enabled():
    sm = enabled_machine()
    assert sm.state == State.OPERATION_ENABLED
    assert sm.statusword & 0x6F == 0x27
    assert sm.is_operation_enabled is True


def test_quick_stop_moves_to_quick_stop_active():
    sm = enabled_machine()
    sm.write_controlword(QUICK_STOP)
    assert sm.state == State.QUICK_STOP_ACTIVE
    assert sm.statusword & 0x6F == 0x07


def test_disable_voltage_returns_to_switch_on_disabled():
    sm = enabled_machine()
    sm.write_controlword(DISABLE_VOLTAGE)
    assert sm.state == State.SWITCH_ON_DISABLED


def test_disable_operation_returns_to_switched_on():
    sm = enabled_machine()
    sm.write_controlword(SWITCH_ON)
    assert sm.state == State.SWITCHED_ON
    assert sm.is_operation_enabled is False


def test_fault_enters_fault_reaction_then_fault():
    sm = enabled_machine()
    sm.set_fault(True)
    assert sm.state == State.FAULT_REACTION_ACTIVE
    assert sm.statusword & 0x4F == 0x0F
    sm.step(0.001)
    assert sm.state == State.FAULT
    assert sm.statusword & 0x4F == 0x08


def test_fault_reset_requires_rising_edge_of_bit7():
    sm = enabled_machine()
    sm.set_fault(True)
    sm.step(0.001)
    sm.write_controlword(FAULT_RESET)
    assert sm.state == State.FAULT
    sm.set_fault(False)
    sm.write_controlword(0x0000)
    sm.write_controlword(FAULT_RESET)
    assert sm.state == State.SWITCH_ON_DISABLED


def test_fault_reset_does_nothing_while_cause_persists():
    sm = enabled_machine()
    sm.set_fault(True)
    sm.step(0.001)
    sm.write_controlword(0x0000)
    sm.write_controlword(FAULT_RESET)
    assert sm.state == State.FAULT


def test_statusword_reflects_flag_bits():
    sm = enabled_machine()
    sm.target_reached = True
    sm.internal_limit_active = True
    sm.warning = True
    assert sm.statusword & (1 << 10)
    assert sm.statusword & (1 << 11)
    assert sm.statusword & (1 << 7)
    assert sm.statusword & (1 << 4)  # voltage enabled は既定 True


def test_voltage_disabled_drops_out_of_operation():
    sm = enabled_machine()
    sm.voltage_enabled = False
    sm.step(0.001)
    assert sm.state == State.SWITCH_ON_DISABLED


def test_two_machines_are_independent():
    a, b = enabled_machine(), Cia402StateMachine()
    b.step(0.001)
    assert a.state == State.OPERATION_ENABLED
    assert b.state == State.SWITCH_ON_DISABLED
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_state_machine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.driver.state_machine'`

- [ ] **Step 3: 最小の実装**

`omsim/driver/state_machine.py`:

```python
"""CiA402 ステートマシン。仕様は HP-5143E 6.1 (p34) / 6.2 (p35)。"""


class State(object):
    NOT_READY = "not-ready-to-switch-on"
    SWITCH_ON_DISABLED = "switch-on-disabled"
    READY_TO_SWITCH_ON = "ready-to-switch-on"
    SWITCHED_ON = "switched-on"
    OPERATION_ENABLED = "operation-enabled"
    QUICK_STOP_ACTIVE = "quick-stop-active"
    FAULT_REACTION_ACTIVE = "fault-reaction-active"
    FAULT = "fault"


# HP-5143E 6.1: Statusword 下位ビットの状態コード (mask, value)
_STATE_CODE = {
    State.NOT_READY: (0x4F, 0x00),
    State.SWITCH_ON_DISABLED: (0x4F, 0x40),
    State.READY_TO_SWITCH_ON: (0x6F, 0x21),
    State.SWITCHED_ON: (0x6F, 0x23),
    State.OPERATION_ENABLED: (0x6F, 0x27),
    State.QUICK_STOP_ACTIVE: (0x6F, 0x07),
    State.FAULT_REACTION_ACTIVE: (0x4F, 0x0F),
    State.FAULT: (0x4F, 0x08),
}

BIT_VOLTAGE_ENABLED = 4
BIT_WARNING = 7
BIT_REMOTE = 9
BIT_TARGET_REACHED = 10
BIT_INTERNAL_LIMIT = 11


def _command(controlword):
    """HP-5143E 6.2 の Controlword コマンド表。"""
    if controlword & 0x87 == 0x06:
        return "shutdown"
    if controlword & 0x8F == 0x0F:
        return "enable-operation"
    if controlword & 0x8F == 0x07:
        return "switch-on"          # disable-operation と同一ビット列
    if controlword & 0x86 == 0x02:
        return "quick-stop"
    if controlword & 0x82 == 0x00:
        return "disable-voltage"
    return None


class Cia402StateMachine(object):
    def __init__(self):
        self.state = State.NOT_READY
        self.voltage_enabled = True
        self.warning = False
        self.target_reached = False
        self.internal_limit_active = False
        self.remote = True
        self._fault_active = False
        self._controlword = 0x0000

    @property
    def controlword(self):
        return self._controlword

    @property
    def is_operation_enabled(self):
        return self.state == State.OPERATION_ENABLED

    @property
    def statusword(self):
        mask, value = _STATE_CODE[self.state]
        word = value
        if self.voltage_enabled:
            word |= 1 << BIT_VOLTAGE_ENABLED
        if self.warning:
            word |= 1 << BIT_WARNING
        if self.remote:
            word |= 1 << BIT_REMOTE
        if self.target_reached:
            word |= 1 << BIT_TARGET_REACHED
        if self.internal_limit_active:
            word |= 1 << BIT_INTERNAL_LIMIT
        return word

    def set_fault(self, active):
        self._fault_active = active
        if active and self.state not in (State.FAULT, State.FAULT_REACTION_ACTIVE):
            self.state = State.FAULT_REACTION_ACTIVE

    def write_controlword(self, value):
        previous = self._controlword
        self._controlword = value
        rising_fault_reset = bool(value & 0x80) and not (previous & 0x80)

        if self.state == State.FAULT:
            if rising_fault_reset and not self._fault_active:
                self.state = State.SWITCH_ON_DISABLED
            return
        if self.state == State.FAULT_REACTION_ACTIVE:
            return

        command = _command(value)
        if command == "disable-voltage":
            self.state = State.SWITCH_ON_DISABLED
        elif command == "quick-stop":
            if self.state == State.OPERATION_ENABLED:
                self.state = State.QUICK_STOP_ACTIVE
            else:
                self.state = State.SWITCH_ON_DISABLED
        elif command == "shutdown":
            if self.state in (
                State.SWITCH_ON_DISABLED, State.SWITCHED_ON, State.OPERATION_ENABLED
            ):
                self.state = State.READY_TO_SWITCH_ON
        elif command == "switch-on":
            if self.state in (State.READY_TO_SWITCH_ON, State.OPERATION_ENABLED):
                self.state = State.SWITCHED_ON
        elif command == "enable-operation":
            if self.state in (State.SWITCHED_ON, State.OPERATION_ENABLED):
                self.state = State.OPERATION_ENABLED

    def step(self, dt):
        if self.state == State.NOT_READY:
            self.state = State.SWITCH_ON_DISABLED
            return
        if self.state == State.FAULT_REACTION_ACTIVE:
            self.state = State.FAULT
            return
        if not self.voltage_enabled and self.state in (
            State.READY_TO_SWITCH_ON, State.SWITCHED_ON,
            State.OPERATION_ENABLED, State.QUICK_STOP_ACTIVE,
        ):
            self.state = State.SWITCH_ON_DISABLED
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_state_machine.py -v`
Expected: 13 passed

- [ ] **Step 5: HP-5143E との突き合わせをコメントに残してコミット**

`docs/oriental_motor/HP-5143E.pdf` の p34-35 を開き、`_STATE_CODE` と `_command` の各行が仕様表と一致するかを目で確認する。差異があればテストを仕様側に合わせて直す。

```bash
git add omsim/driver/state_machine.py tests/unit/test_state_machine.py
git commit -m "feat: CiA402 ステートマシンと Statusword"
```

---

## Task 14: 単位系の変換（6091h / 608Fh / 60A8h / 60A9h）

**Files:**
- Create: `omsim/driver/units.py`
- Test: `tests/unit/test_units.py`

**Interfaces:**
- Consumes: `ObjectAccessError`, `ABORT_VALUE_RANGE`
- Produces:
  - `UnitConverter(encoder_increments: int = 3600, motor_revolutions: int = 1, gear_motor_revolutions: int = 1, gear_shaft_revolutions: int = 1)`
  - `.gear_ratio: float` — `gear_motor_revolutions / gear_shaft_revolutions`（減速比。pitakuru は 100）
  - `.increments_per_shaft_rev: float`
  - `.rpm_to_internal(rpm: float) -> float` — 出力軸 r/min → 内部速度[increment/s]
  - `.internal_to_rpm(value: float) -> float`
  - `.set_gear_ratio(motor_revolutions: int, shaft_revolutions: int) -> None` — `shaft_revolutions == 0` は `ABORT_VALUE_RANGE`
  - `.set_encoder_resolution(increments: int, motor_revolutions: int) -> None` — どちらかが 0 なら `ABORT_VALUE_RANGE`

`6091h` Gear ratio は sub1 = motor revolutions / sub2 = shaft revolutions、`608Fh` Position encoder resolution は sub1 = encoder increments / sub2 = motor revolutions。単位の扱いは `docs/oriental_motor/HP-5141J.pdf` 第1章1節「単位設定」（p12）と `HP-5143E.pdf` の該当オブジェクト定義で確認する。

内部表現は **increment/s** に統一する。理由: `6064h` Position actual value と `606Ch` Velocity actual value の生の単位を 1 つの基準で扱えるようにし、pv と pp で変換規則を共有するため。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_units.py`:

```python
import pytest

from omsim.driver.errors import ABORT_VALUE_RANGE, ObjectAccessError
from omsim.driver.units import UnitConverter


def test_default_gear_ratio_is_one_to_one():
    assert UnitConverter().gear_ratio == 1.0


def test_gear_ratio_of_one_hundred_matches_pitakuru_reduction():
    conv = UnitConverter()
    conv.set_gear_ratio(100, 1)
    assert conv.gear_ratio == 100.0


def test_increments_per_shaft_revolution_includes_gear_and_encoder():
    conv = UnitConverter(encoder_increments=3600, motor_revolutions=1)
    conv.set_gear_ratio(100, 1)
    assert conv.increments_per_shaft_rev == 360000.0


def test_rpm_round_trips_through_internal_units():
    conv = UnitConverter(encoder_increments=3600, motor_revolutions=1)
    conv.set_gear_ratio(100, 1)
    internal = conv.rpm_to_internal(30.0)
    assert abs(conv.internal_to_rpm(internal) - 30.0) < 1e-9


def test_thirty_rpm_at_gear_100_is_180000_increments_per_second():
    conv = UnitConverter(encoder_increments=3600, motor_revolutions=1)
    conv.set_gear_ratio(100, 1)
    assert abs(conv.rpm_to_internal(30.0) - 180000.0) < 1e-6


def test_zero_shaft_revolutions_is_rejected():
    conv = UnitConverter()
    with pytest.raises(ObjectAccessError) as exc:
        conv.set_gear_ratio(100, 0)
    assert exc.value.abort_code == ABORT_VALUE_RANGE


def test_zero_encoder_increments_is_rejected():
    conv = UnitConverter()
    with pytest.raises(ObjectAccessError) as exc:
        conv.set_encoder_resolution(0, 1)
    assert exc.value.abort_code == ABORT_VALUE_RANGE


def test_rejected_write_leaves_previous_value_intact():
    conv = UnitConverter()
    conv.set_gear_ratio(100, 1)
    with pytest.raises(ObjectAccessError):
        conv.set_gear_ratio(100, 0)
    assert conv.gear_ratio == 100.0


def test_two_converters_are_independent():
    a, b = UnitConverter(), UnitConverter()
    a.set_gear_ratio(100, 1)
    assert b.gear_ratio == 1.0
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_units.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.driver.units'`

- [ ] **Step 3: 最小の実装**

`omsim/driver/units.py`:

```python
"""単位変換。HP-5141J 第1章1節「単位設定」(p12)、6091h / 608Fh。

内部表現は increment/s に統一する。
"""
from omsim.driver.errors import ABORT_VALUE_RANGE, ObjectAccessError


class UnitConverter(object):
    def __init__(
        self,
        encoder_increments=3600,
        motor_revolutions=1,
        gear_motor_revolutions=1,
        gear_shaft_revolutions=1,
    ):
        self.encoder_increments = encoder_increments
        self.motor_revolutions = motor_revolutions
        self.gear_motor_revolutions = gear_motor_revolutions
        self.gear_shaft_revolutions = gear_shaft_revolutions

    @property
    def gear_ratio(self):
        return float(self.gear_motor_revolutions) / float(self.gear_shaft_revolutions)

    @property
    def increments_per_shaft_rev(self):
        per_motor_rev = float(self.encoder_increments) / float(self.motor_revolutions)
        return per_motor_rev * self.gear_ratio

    def rpm_to_internal(self, rpm):
        return float(rpm) / 60.0 * self.increments_per_shaft_rev

    def internal_to_rpm(self, value):
        return float(value) * 60.0 / self.increments_per_shaft_rev

    def set_gear_ratio(self, motor_revolutions, shaft_revolutions):
        if motor_revolutions <= 0 or shaft_revolutions <= 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6091h に 0 以下は設定できません")
        self.gear_motor_revolutions = motor_revolutions
        self.gear_shaft_revolutions = shaft_revolutions

    def set_encoder_resolution(self, increments, motor_revolutions):
        if increments <= 0 or motor_revolutions <= 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "608Fh に 0 以下は設定できません")
        self.encoder_increments = increments
        self.motor_revolutions = motor_revolutions
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_units.py -v`
Expected: 9 passed

- [ ] **Step 5: コミット**

```bash
git add omsim/driver/units.py tests/unit/test_units.py
git commit -m "feat: 単位変換 (6091h/608Fh)"
```

---

## Task 15: 台形加減速プロファイル

**Files:**
- Create: `omsim/driver/profile.py`
- Test: `tests/unit/test_profile.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `TrapezoidProfile(acceleration: float = 1000.0, deceleration: float = 1000.0)`
    `acceleration` / `deceleration` の単位は increment/s^2、常に正の値
  - `.command: float` — 現在の指令速度[increment/s]（符号付き）
  - `.target: float` — 目標速度[increment/s]（符号付き）
  - `.set_target(value: float) -> None`
  - `.step(dt: float) -> float` — 1 ステップ進めて新しい `command` を返す
  - `.at_target: bool` — 指令が目標に到達したか
  - `.reset(command: float = 0.0) -> None`
  - 加速側（絶対値が増える方向）は `acceleration`、減速側（絶対値が減る方向）は `deceleration` を使う。符号反転をまたぐ場合は 0 を経由し、0 までは `deceleration`、0 からは `acceleration`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_profile.py`:

```python
from omsim.driver.profile import TrapezoidProfile


def run(profile, seconds):
    steps = int(round(seconds / 0.001))
    for _ in range(steps):
        profile.step(0.001)
    return profile.command


def test_starts_at_zero():
    profile = TrapezoidProfile()
    assert profile.command == 0.0
    assert profile.at_target is True


def test_accelerates_at_the_configured_rate():
    profile = TrapezoidProfile(acceleration=1000.0)
    profile.set_target(1000.0)
    assert abs(run(profile, 0.5) - 500.0) < 1e-6


def test_stops_accelerating_at_the_target():
    profile = TrapezoidProfile(acceleration=1000.0)
    profile.set_target(100.0)
    assert abs(run(profile, 1.0) - 100.0) < 1e-6
    assert profile.at_target is True


def test_decelerates_with_the_deceleration_rate():
    profile = TrapezoidProfile(acceleration=1000.0, deceleration=500.0)
    profile.set_target(1000.0)
    run(profile, 2.0)
    profile.set_target(0.0)
    assert abs(run(profile, 1.0) - 500.0) < 1e-6


def test_reaches_zero_exactly_without_overshoot():
    profile = TrapezoidProfile(acceleration=1000.0, deceleration=1000.0)
    profile.set_target(100.0)
    run(profile, 1.0)
    profile.set_target(0.0)
    assert run(profile, 1.0) == 0.0


def test_negative_target_accelerates_in_reverse():
    profile = TrapezoidProfile(acceleration=1000.0)
    profile.set_target(-1000.0)
    assert abs(run(profile, 0.5) + 500.0) < 1e-6


def test_sign_reversal_passes_through_zero_using_deceleration_first():
    profile = TrapezoidProfile(acceleration=1000.0, deceleration=2000.0)
    profile.set_target(1000.0)
    run(profile, 2.0)
    profile.set_target(-1000.0)
    # 1000 -> 0 は deceleration 2000 なので 0.5s、その後 0 -> -500 は acceleration 1000 で 0.5s
    assert abs(run(profile, 0.5)) < 1e-6
    assert abs(run(profile, 0.5) + 500.0) < 1e-6


def test_reset_clears_command_and_target():
    profile = TrapezoidProfile()
    profile.set_target(500.0)
    run(profile, 0.1)
    profile.reset()
    assert profile.command == 0.0
    assert profile.target == 0.0
    assert profile.at_target is True


def test_two_profiles_are_independent():
    a = TrapezoidProfile(acceleration=1000.0)
    b = TrapezoidProfile(acceleration=1000.0)
    a.set_target(1000.0)
    run(a, 0.5)
    assert b.command == 0.0
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.driver.profile'`

- [ ] **Step 3: 最小の実装**

`omsim/driver/profile.py`:

```python
"""台形加減速の指令速度生成。単位は increment/s、加減速度は increment/s^2。

停止方法の詳細は HP-5141J 第1章3節「停止動作」(p34)。ここでは加減速の骨格のみを持つ。
"""


class TrapezoidProfile(object):
    def __init__(self, acceleration=1000.0, deceleration=1000.0):
        self.acceleration = float(acceleration)
        self.deceleration = float(deceleration)
        self.command = 0.0
        self.target = 0.0

    @property
    def at_target(self):
        return self.command == self.target

    def set_target(self, value):
        self.target = float(value)

    def reset(self, command=0.0):
        self.command = float(command)
        self.target = float(command)

    def step(self, dt):
        if self.command == self.target:
            return self.command

        # 符号反転をまたぐ場合は 0 で折り返す
        crossing_zero = self.command * self.target < 0.0
        waypoint = 0.0 if crossing_zero else self.target

        if abs(waypoint) > abs(self.command) and self.command * waypoint >= 0.0:
            rate = self.acceleration
        else:
            rate = self.deceleration

        delta = rate * dt
        if waypoint > self.command:
            self.command = min(self.command + delta, waypoint)
        else:
            self.command = max(self.command - delta, waypoint)
        return self.command
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_profile.py -v`
Expected: 9 passed

- [ ] **Step 5: コミット**

```bash
git add omsim/driver/profile.py tests/unit/test_profile.py
git commit -m "feat: 台形加減速プロファイル"
```

---

## Task 16: MotorPlant（1 次遅れ追従・位置積分・トルク推定）

**Files:**
- Create: `omsim/driver/motor_plant.py`
- Test: `tests/unit/test_motor_plant.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `MotorPlant(time_constant: float = 0.02, load_torque_permille: float = 0.0, inertia_gain: float = 1e-4)`
  - `.velocity: float` — 実速度[increment/s]
  - `.position: int` — 実位置[increment]（整数に丸めて保持。`6064h` に載せるため）
  - `.torque_permille: float` — トルク推定[定格の 0.1%]（`6077h` の単位に合わせる）
  - `.excited: bool` — 励磁状態。`False` の間は指令に追従せず自然に 0 へ落ちる
  - `.step(dt: float, command_velocity: float) -> None`
  - `.preset_position(value: int) -> None` — 位置プリセット（`40C5h` P-PRESET 用、P5 で使う）
  - `.reset() -> None`

トルクは `inertia_gain * dv/dt + load_torque_permille` の単純式。実機の値と一致させることは目的ではなく、加速中にトルクが増えて定常で負荷分に落ち着くという挙動を再現することが目的（設計書 5.6）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_motor_plant.py`:

```python
from omsim.driver.motor_plant import MotorPlant


def run(plant, seconds, command):
    steps = int(round(seconds / 0.001))
    for _ in range(steps):
        plant.step(0.001, command)


def test_starts_at_rest():
    plant = MotorPlant()
    assert plant.velocity == 0.0
    assert plant.position == 0
    assert plant.excited is False


def test_does_not_move_while_not_excited():
    plant = MotorPlant()
    run(plant, 1.0, 1000.0)
    assert plant.velocity == 0.0
    assert plant.position == 0


def test_follows_command_with_first_order_lag():
    plant = MotorPlant(time_constant=0.02)
    plant.excited = True
    run(plant, 0.02, 1000.0)
    # 時定数 1 本ぶんで 63% 前後
    assert 550.0 < plant.velocity < 700.0


def test_settles_at_the_command_velocity():
    plant = MotorPlant(time_constant=0.02)
    plant.excited = True
    run(plant, 1.0, 1000.0)
    assert abs(plant.velocity - 1000.0) < 1.0


def test_position_integrates_velocity():
    plant = MotorPlant(time_constant=0.001)
    plant.excited = True
    run(plant, 1.0, 1000.0)
    assert 950 <= plant.position <= 1000


def test_position_is_an_integer():
    plant = MotorPlant(time_constant=0.001)
    plant.excited = True
    run(plant, 0.1, 333.0)
    assert isinstance(plant.position, int)


def test_reverse_command_drives_position_negative():
    plant = MotorPlant(time_constant=0.001)
    plant.excited = True
    run(plant, 1.0, -1000.0)
    assert plant.position < 0


def test_losing_excitation_coasts_to_zero():
    plant = MotorPlant(time_constant=0.02)
    plant.excited = True
    run(plant, 1.0, 1000.0)
    plant.excited = False
    run(plant, 1.0, 1000.0)
    assert abs(plant.velocity) < 1.0


def test_torque_rises_while_accelerating_and_settles_to_load():
    plant = MotorPlant(time_constant=0.02, load_torque_permille=50.0, inertia_gain=1e-3)
    plant.excited = True
    run(plant, 0.005, 100000.0)
    accelerating = plant.torque_permille
    run(plant, 2.0, 100000.0)
    settled = plant.torque_permille
    assert accelerating > settled
    assert abs(settled - 50.0) < 1.0


def test_preset_position_overwrites_position():
    plant = MotorPlant()
    plant.preset_position(12345)
    assert plant.position == 12345


def test_reset_returns_to_rest():
    plant = MotorPlant(time_constant=0.001)
    plant.excited = True
    run(plant, 0.5, 1000.0)
    plant.reset()
    assert plant.velocity == 0.0
    assert plant.position == 0


def test_two_plants_are_independent():
    a, b = MotorPlant(time_constant=0.001), MotorPlant(time_constant=0.001)
    a.excited = True
    run(a, 0.5, 1000.0)
    assert b.velocity == 0.0
    assert b.position == 0
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_motor_plant.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.driver.motor_plant'`

- [ ] **Step 3: 最小の実装**

`omsim/driver/motor_plant.py`:

```python
"""モーターの物理モデル。指令速度への 1 次遅れ追従 + 位置積分 + トルク推定。

設計書 5.6 のとおり、実機のトルク値と一致させることは目的ではない。
加速中にトルクが増え、定常では負荷分に落ち着くという挙動を再現する。
"""


class MotorPlant(object):
    def __init__(self, time_constant=0.02, load_torque_permille=0.0, inertia_gain=1e-4):
        self.time_constant = float(time_constant)
        self.load_torque_permille = float(load_torque_permille)
        self.inertia_gain = float(inertia_gain)
        self.excited = False
        self.velocity = 0.0
        self.torque_permille = 0.0
        self._position = 0.0

    @property
    def position(self):
        return int(self._position)

    def preset_position(self, value):
        self._position = float(value)

    def reset(self):
        self.velocity = 0.0
        self.torque_permille = 0.0
        self._position = 0.0

    def step(self, dt, command_velocity):
        target = float(command_velocity) if self.excited else 0.0
        previous = self.velocity

        if self.time_constant <= 0.0:
            self.velocity = target
        else:
            alpha = min(1.0, dt / self.time_constant)
            self.velocity += (target - self.velocity) * alpha

        self._position += self.velocity * dt

        if self.excited:
            acceleration = (self.velocity - previous) / dt if dt > 0.0 else 0.0
            self.torque_permille = self.inertia_gain * acceleration + self.load_torque_permille
        else:
            self.torque_permille = 0.0
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_motor_plant.py -v`
Expected: 12 passed

`test_follows_command_with_first_order_lag` の範囲（550〜700）は 1ms 離散化した 1 次遅れの実測値に依存する。落ちた場合は実測値を出して範囲を実装に合わせる。ただし「時定数 1 本で 50%〜75% の間」という性質は崩さない。

- [ ] **Step 5: コミット**

```bash
git add omsim/driver/motor_plant.py tests/unit/test_motor_plant.py
git commit -m "feat: MotorPlant (1次遅れ追従・位置積分・トルク推定)"
```

---

## Task 17: AlarmModel（アラーム基礎と 1003h 履歴）

**Files:**
- Create: `omsim/driver/alarm_model.py`
- Test: `tests/unit/test_alarm_model.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `AlarmModel(history_size: int = 10)`
  - `.raise_alarm(alarm_code: int, emcy_code: int, error_register: int = 0x01) -> None`
  - `.active_alarm: Optional[int]` — 現在のアラームコード（無ければ `None`）
  - `.is_active: bool`
  - `.error_code: int` — `603Fh` に載せる値（アラーム無しは 0）
  - `.error_register: int` — `1001h`（アラーム無しは 0）
  - `.reset() -> bool` — 解除できたら `True`。解除できない（原因継続中）なら `False`
  - `.set_cause_cleared(cleared: bool) -> None` — 原因が消えたかを外から設定する
  - `.history: List[int]` — 新しい順のアラームコード。最大 `history_size` 件
  - `.clear_history() -> None`
  - `.pop_pending_emcy() -> Optional[Tuple[int, int]]` — 未送信の EMCY を 1 件取り出す `(emcy_code, error_register)`。無ければ `None`
  - `ALARM_OVERLOAD = 0x30` / `EMCY_OVERLOAD = 0x2310`（アラームコードと EMCY コードの対応の 1 例。全コードは P6 で `HP-5141J.pdf` 第8章 p420 から表として起こす）

このフェーズでは「発生・解除・履歴・EMCY 発行のしくみ」を作る。全アラームコードの網羅は P6。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_alarm_model.py`:

```python
from omsim.driver.alarm_model import ALARM_OVERLOAD, EMCY_OVERLOAD, AlarmModel


def test_starts_clean():
    model = AlarmModel()
    assert model.is_active is False
    assert model.active_alarm is None
    assert model.error_code == 0
    assert model.error_register == 0
    assert model.history == []


def test_raising_sets_active_alarm_and_codes():
    model = AlarmModel()
    model.raise_alarm(ALARM_OVERLOAD, EMCY_OVERLOAD, error_register=0x21)
    assert model.is_active is True
    assert model.active_alarm == ALARM_OVERLOAD
    assert model.error_code == EMCY_OVERLOAD
    assert model.error_register == 0x21


def test_raising_queues_an_emcy():
    model = AlarmModel()
    model.raise_alarm(ALARM_OVERLOAD, EMCY_OVERLOAD, error_register=0x21)
    assert model.pop_pending_emcy() == (EMCY_OVERLOAD, 0x21)
    assert model.pop_pending_emcy() is None


def test_raising_appends_to_history_newest_first():
    model = AlarmModel()
    model.raise_alarm(0x30, 0x2310)
    model.set_cause_cleared(True)
    model.reset()
    model.raise_alarm(0x31, 0x2311)
    assert model.history[0] == 0x31
    assert model.history[1] == 0x30


def test_history_is_bounded():
    model = AlarmModel(history_size=3)
    for code in range(0x30, 0x38):
        model.raise_alarm(code, 0x2310)
        model.set_cause_cleared(True)
        model.reset()
    assert len(model.history) == 3


def test_reset_fails_while_cause_persists():
    model = AlarmModel()
    model.raise_alarm(ALARM_OVERLOAD, EMCY_OVERLOAD)
    assert model.reset() is False
    assert model.is_active is True


def test_reset_succeeds_after_cause_cleared():
    model = AlarmModel()
    model.raise_alarm(ALARM_OVERLOAD, EMCY_OVERLOAD)
    model.set_cause_cleared(True)
    assert model.reset() is True
    assert model.is_active is False
    assert model.error_code == 0
    assert model.error_register == 0


def test_reset_queues_an_error_reset_emcy():
    model = AlarmModel()
    model.raise_alarm(ALARM_OVERLOAD, EMCY_OVERLOAD)
    model.pop_pending_emcy()
    model.set_cause_cleared(True)
    model.reset()
    assert model.pop_pending_emcy() == (0x0000, 0x00)


def test_reset_on_clean_model_is_a_no_op():
    model = AlarmModel()
    assert model.reset() is True
    assert model.pop_pending_emcy() is None


def test_second_alarm_while_active_is_ignored():
    model = AlarmModel()
    model.raise_alarm(0x30, 0x2310)
    model.raise_alarm(0x31, 0x2311)
    assert model.active_alarm == 0x30
    assert model.history == [0x30]


def test_clear_history_empties_the_list_but_keeps_active_alarm():
    model = AlarmModel()
    model.raise_alarm(0x30, 0x2310)
    model.clear_history()
    assert model.history == []
    assert model.active_alarm == 0x30


def test_two_models_are_independent():
    a, b = AlarmModel(), AlarmModel()
    a.raise_alarm(0x30, 0x2310)
    assert b.is_active is False
    assert b.history == []
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_alarm_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.driver.alarm_model'`

- [ ] **Step 3: 最小の実装**

`omsim/driver/alarm_model.py`:

```python
"""アラームの発生・解除・履歴と EMCY の発行。

アラーム全コードは HP-5141J 第8章 (p420) から P6 で表に起こす。
このフェーズはしくみだけを作り、代表として過負荷のみ定義する。
"""
import collections

ALARM_OVERLOAD = 0x30
EMCY_OVERLOAD = 0x2310
EMCY_ERROR_RESET = 0x0000


class AlarmModel(object):
    def __init__(self, history_size=10):
        self._history = collections.deque(maxlen=history_size)
        self._pending_emcy = collections.deque()
        self.active_alarm = None
        self.error_code = 0
        self.error_register = 0
        self._cause_cleared = False

    @property
    def is_active(self):
        return self.active_alarm is not None

    @property
    def history(self):
        return list(self._history)

    def set_cause_cleared(self, cleared):
        self._cause_cleared = bool(cleared)

    def raise_alarm(self, alarm_code, emcy_code, error_register=0x01):
        if self.is_active:
            return
        self.active_alarm = alarm_code
        self.error_code = emcy_code
        self.error_register = error_register
        self._cause_cleared = False
        self._history.appendleft(alarm_code)
        self._pending_emcy.append((emcy_code, error_register))

    def reset(self):
        if not self.is_active:
            return True
        if not self._cause_cleared:
            return False
        self.active_alarm = None
        self.error_code = 0
        self.error_register = 0
        self._pending_emcy.append((EMCY_ERROR_RESET, 0x00))
        return True

    def clear_history(self):
        self._history.clear()

    def pop_pending_emcy(self):
        if not self._pending_emcy:
            return None
        return self._pending_emcy.popleft()
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_alarm_model.py -v`
Expected: 12 passed

- [ ] **Step 5: コミット**

```bash
git add omsim/driver/alarm_model.py tests/unit/test_alarm_model.py
git commit -m "feat: AlarmModel (発生・解除・履歴・EMCY 発行)"
```

---

## Task 18: pv モードを DriverModel に組み込む

**Files:**
- Modify: `omsim/driver/model.py`（Task 5 で作ったファイルを全面的に書き足す）
- Test: `tests/unit/test_driver_pv.py`

**Interfaces:**
- Consumes: `Cia402StateMachine`, `State`, `UnitConverter`, `TrapezoidProfile`, `MotorPlant`, `AlarmModel`, `ObjectRouter`, `ObjectAccessError`
- Produces（`DriverModel` に追加）:
  - 属性 `state_machine`, `units`, `profile`, `plant`, `alarms`
  - 対応オブジェクト: `1001h`(ro) `1008h`(ro) `603Fh`(ro) `6040h`(rw) `6041h`(ro) `6060h`(rw) `6061h`(ro)
    `6064h`(ro) `606Bh`(ro) `606Ch`(ro) `606Dh`(rw) `606Fh`(rw) `6077h`(ro) `6083h`(rw) `6084h`(rw)
    `608Fh`sub1/sub2(rw) `6091h`sub1/sub2(rw) `60FFh`(rw) `6502h`(ro) `40C0h`(wo アラームリセット)
  - `MODE_PV = 3`。`6060h` に pv 以外を書くと `NotImplementedError`（P4 で pp/hm/tq を追加するまで）
  - `.snapshot()` のキー: `node_id`, `sim_time`, `nmt_state` は持たず、`state`, `statusword`, `mode`,
    `target_velocity_rpm`, `command_velocity_rpm`, `actual_velocity_rpm`, `actual_position`,
    `torque_permille`, `alarm`, `alarm_history`
  - `6041h` bit10 Target reached は「実速度が指令速度に `606Dh` Velocity window 以内で一致」で立てる
  - `6041h` bit12 は pv では「速度 0 かどうか」（`606Fh` Velocity threshold 以下）
  - 単位: `60FFh` / `606Bh` / `606Ch` は **r/min（出力軸）**、`6064h` は increment。
    `6083h` / `6084h` は **r/min/s（出力軸）**

`606Ch` の単位は本来 `60A9h` SI unit velocity に従うが、pitakuru が r/min で扱っていることと `HP-5141J.pdf` 第1章1節（p12）の既定に合わせて r/min とする。`60A9h` 対応は P4。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_driver_pv.py`:

```python
import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import MODE_PV, DriverModel
from omsim.driver.state_machine import State

SHUTDOWN = 0x0006
SWITCH_ON = 0x0007
ENABLE_OPERATION = 0x000F


def enabled_model(**kwargs):
    model = DriverModel(node_id=1, **kwargs)
    model.step(0.001)
    model.write_object(0x6060, 0, MODE_PV)
    model.write_object(0x6040, 0, SHUTDOWN)
    model.write_object(0x6040, 0, SWITCH_ON)
    model.write_object(0x6040, 0, ENABLE_OPERATION)
    return model


def run(model, seconds):
    for _ in range(int(round(seconds / 0.001))):
        model.step(0.001)


def test_mode_display_follows_mode_of_operation():
    model = enabled_model()
    assert model.read_object(0x6061) == MODE_PV


def test_unsupported_mode_is_reported_as_not_implemented():
    model = DriverModel(node_id=1)
    with pytest.raises(NotImplementedError):
        model.write_object(0x6060, 0, 1)


def test_statusword_shows_operation_enabled():
    model = enabled_model()
    assert model.read_object(0x6041) & 0x6F == 0x27
    assert model.state_machine.state == State.OPERATION_ENABLED


def test_motor_is_excited_only_in_operation_enabled():
    model = enabled_model()
    assert model.plant.excited is True
    model.write_object(0x6040, 0, SWITCH_ON)
    model.step(0.001)
    assert model.plant.excited is False


def test_does_not_move_before_operation_enabled():
    model = DriverModel(node_id=1)
    model.step(0.001)
    model.write_object(0x6060, 0, MODE_PV)
    model.write_object(0x60FF, 0, 100)
    run(model, 1.0)
    assert model.read_object(0x606C) == 0
    assert model.read_object(0x6064) == 0


def test_reaches_target_velocity_in_rpm():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    model.write_object(0x60FF, 0, 100)
    run(model, 3.0)
    assert abs(model.read_object(0x606C) - 100) <= 1


def test_velocity_demand_follows_the_acceleration_ramp():
    model = enabled_model()
    model.write_object(0x6083, 0, 100)  # 100 r/min/s
    model.write_object(0x60FF, 0, 100)
    run(model, 0.5)
    demand = model.read_object(0x606B)
    assert 40 <= demand <= 60


def test_position_advances_while_running_forward():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x60FF, 0, 100)
    run(model, 1.0)
    assert model.read_object(0x6064) > 0


def test_negative_target_runs_in_reverse():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    model.write_object(0x60FF, 0, -100)
    run(model, 3.0)
    assert abs(model.read_object(0x606C) + 100) <= 1
    assert model.read_object(0x6064) < 0


def test_target_reached_bit_sets_when_settled():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    model.write_object(0x606D, 0, 2)  # velocity window 2 r/min
    model.write_object(0x60FF, 0, 100)
    run(model, 3.0)
    assert model.read_object(0x6041) & (1 << 10)


def test_target_reached_bit_clears_while_accelerating():
    model = enabled_model()
    model.write_object(0x6083, 0, 10)
    model.write_object(0x606D, 0, 2)
    model.write_object(0x60FF, 0, 3000)
    run(model, 0.2)
    assert not model.read_object(0x6041) & (1 << 10)


def test_gear_ratio_changes_the_position_scale():
    slow = enabled_model()
    slow.write_object(0x6091, 1, 1)
    slow.write_object(0x6091, 2, 1)
    slow.write_object(0x6083, 0, 6000)
    slow.write_object(0x60FF, 0, 60)
    run(slow, 2.0)

    geared = enabled_model()
    geared.write_object(0x6091, 1, 100)
    geared.write_object(0x6091, 2, 1)
    geared.write_object(0x6083, 0, 6000)
    geared.write_object(0x60FF, 0, 60)
    run(geared, 2.0)

    assert geared.read_object(0x6064) > slow.read_object(0x6064) * 50


def test_torque_actual_value_is_readable():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x60FF, 0, 100)
    run(model, 1.0)
    assert isinstance(model.read_object(0x6077), int)


def test_supported_drive_modes_advertises_pv():
    model = DriverModel(node_id=1)
    assert model.read_object(0x6502) & (1 << 2)


def test_statusword_is_read_only():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError):
        model.write_object(0x6041, 0, 0)


def test_alarm_drops_the_state_machine_into_fault():
    model = enabled_model()
    model.inject_alarm(0x30, 0x2310)
    model.step(0.001)
    model.step(0.001)
    assert model.read_object(0x6041) & 0x4F == 0x08
    assert model.read_object(0x603F) == 0x2310
    assert model.read_object(0x1001) != 0


def test_alarm_stops_the_motor():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x60FF, 0, 100)
    run(model, 1.0)
    model.inject_alarm(0x30, 0x2310)
    run(model, 1.0)
    assert abs(model.read_object(0x606C)) <= 1


def test_alarm_reset_via_40c0_clears_the_fault():
    model = enabled_model()
    model.inject_alarm(0x30, 0x2310)
    run(model, 0.01)
    model.alarms.set_cause_cleared(True)
    model.write_object(0x40C0, 0, 1)
    model.write_object(0x6040, 0, 0x0000)
    model.write_object(0x6040, 0, 0x0080)
    model.step(0.001)
    assert model.read_object(0x6041) & 0x4F == 0x40
    assert model.read_object(0x603F) == 0


def test_snapshot_exposes_the_monitor_values():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x60FF, 0, 100)
    run(model, 2.0)
    snap = model.snapshot()
    assert snap["node_id"] == 1
    assert snap["mode"] == MODE_PV
    assert snap["state"] == State.OPERATION_ENABLED
    assert abs(snap["target_velocity_rpm"] - 100) < 1e-9
    assert abs(snap["actual_velocity_rpm"] - 100) <= 1
    assert "statusword" in snap
    assert "actual_position" in snap
    assert "torque_permille" in snap
    assert snap["alarm"] is None
    assert snap["alarm_history"] == []


def test_two_models_run_at_different_speeds():
    a = enabled_model()
    b = enabled_model()
    for model, target in ((a, 100), (b, 50)):
        model.write_object(0x6083, 0, 6000)
        model.write_object(0x6084, 0, 6000)
        model.write_object(0x60FF, 0, target)
    for _ in range(3000):
        a.step(0.001)
        b.step(0.001)
    assert abs(a.read_object(0x606C) - 100) <= 1
    assert abs(b.read_object(0x606C) - 50) <= 1
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/unit/test_driver_pv.py -v`
Expected: FAIL — `ImportError: cannot import name 'MODE_PV' from 'omsim.driver.model'`

- [ ] **Step 3: `omsim/driver/model.py` を書き換える**

```python
"""BLVD-KRD ドライバの挙動モデル。can / canopen を import しないこと。

参照: HP-5143E 7.2 Profile Velocity Mode (p37)、HP-5141J 第1章 (p12-48)
"""
from omsim.driver.alarm_model import AlarmModel
from omsim.driver.errors import ABORT_VALUE_RANGE, ObjectAccessError
from omsim.driver.motor_plant import MotorPlant
from omsim.driver.objects import ObjectRouter
from omsim.driver.profile import TrapezoidProfile
from omsim.driver.state_machine import Cia402StateMachine, State
from omsim.driver.units import UnitConverter

MODE_PV = 3
MODE_PP = 1
MODE_TQ = 4
MODE_HM = 6

# 6502h Supported drive modes: bit0=pp, bit2=pv, bit3=tq, bit5=hm
SUPPORTED_DRIVE_MODES = (1 << 0) | (1 << 2) | (1 << 3) | (1 << 5)

_INT32_MIN, _INT32_MAX = -(2 ** 31), 2 ** 31 - 1


def _clamp_int32(value):
    return max(_INT32_MIN, min(_INT32_MAX, int(value)))


class DriverModel(object):
    """1 台のドライバ。状態は全てインスタンス変数に持つ。"""

    router = ObjectRouter()

    DEVICE_NAME = "BLVD-KRD"

    def __init__(self, node_id, time_constant=0.02, load_torque_permille=0.0):
        self.node_id = node_id
        self.sim_time = 0.0

        self.state_machine = Cia402StateMachine()
        self.units = UnitConverter()
        self.profile = TrapezoidProfile()
        self.plant = MotorPlant(
            time_constant=time_constant, load_torque_permille=load_torque_permille
        )
        self.alarms = AlarmModel()

        self.mode = MODE_PV
        self.target_velocity_rpm = 0.0
        self.profile_acceleration_rpm_s = 1000.0
        self.profile_deceleration_rpm_s = 1000.0
        self.velocity_window_rpm = 1.0
        self.velocity_threshold_rpm = 1.0

    # --- 外向きの窓口は以下の 4 つだけ ---

    def read_object(self, index, sub=0):
        return self.router.read(self, index, sub)

    def write_object(self, index, sub=0, value=0):
        self.router.write(self, index, sub, value)

    def step(self, dt):
        self.sim_time += dt

        if self.alarms.is_active:
            self.state_machine.set_fault(True)
        self.state_machine.step(dt)

        excited = self.state_machine.is_operation_enabled
        self.plant.excited = excited

        self.profile.acceleration = self.units.rpm_to_internal(
            self.profile_acceleration_rpm_s)
        self.profile.deceleration = self.units.rpm_to_internal(
            self.profile_deceleration_rpm_s)

        if excited:
            self.profile.set_target(self.units.rpm_to_internal(self.target_velocity_rpm))
        else:
            self.profile.set_target(0.0)
            if self.state_machine.state in (State.FAULT, State.SWITCH_ON_DISABLED):
                self.profile.reset(0.0)

        self.profile.step(dt)
        self.plant.step(dt, self.profile.command)

        error_rpm = abs(self.actual_velocity_rpm - self.command_velocity_rpm)
        self.state_machine.target_reached = (
            excited and self.profile.at_target and error_rpm <= self.velocity_window_rpm
        )

    def snapshot(self):
        return {
            "node_id": self.node_id,
            "sim_time": self.sim_time,
            "state": self.state_machine.state,
            "statusword": self.state_machine.statusword,
            "mode": self.mode,
            "target_velocity_rpm": self.target_velocity_rpm,
            "command_velocity_rpm": self.command_velocity_rpm,
            "actual_velocity_rpm": self.actual_velocity_rpm,
            "actual_position": self.plant.position,
            "torque_permille": self.plant.torque_permille,
            "alarm": self.alarms.active_alarm,
            "alarm_history": self.alarms.history,
        }

    # --- テストと Web からアラームを注入する口 ---

    def inject_alarm(self, alarm_code, emcy_code, error_register=0x21):
        self.alarms.raise_alarm(alarm_code, emcy_code, error_register)

    # --- 派生値 ---

    @property
    def command_velocity_rpm(self):
        return self.units.internal_to_rpm(self.profile.command)

    @property
    def actual_velocity_rpm(self):
        return self.units.internal_to_rpm(self.plant.velocity)

    # --- 通信オブジェクト ---

    @router.reader(0x1001)
    def _read_error_register(self, sub):
        return self.alarms.error_register

    @router.reader(0x1008)
    def _read_device_name(self, sub):
        return self.DEVICE_NAME

    @router.reader(0x603F)
    def _read_error_code(self, sub):
        return self.alarms.error_code

    # --- CiA402 ---

    @router.reader(0x6040)
    def _read_controlword(self, sub):
        return self.state_machine.controlword

    @router.writer(0x6040)
    def _write_controlword(self, sub, value):
        self.state_machine.write_controlword(int(value) & 0xFFFF)

    @router.reader(0x6041)
    def _read_statusword(self, sub):
        return self.state_machine.statusword

    @router.reader(0x6060)
    def _read_mode(self, sub):
        return self.mode

    @router.writer(0x6060)
    def _write_mode(self, sub, value):
        mode = int(value)
        if mode != MODE_PV:
            raise NotImplementedError(
                "運転モード {} は P4 で実装する (6060h)".format(mode))
        self.mode = mode

    @router.reader(0x6061)
    def _read_mode_display(self, sub):
        return self.mode

    @router.reader(0x6064)
    def _read_position_actual(self, sub):
        return _clamp_int32(self.plant.position)

    @router.reader(0x606B)
    def _read_velocity_demand(self, sub):
        return _clamp_int32(round(self.command_velocity_rpm))

    @router.reader(0x606C)
    def _read_velocity_actual(self, sub):
        return _clamp_int32(round(self.actual_velocity_rpm))

    @router.reader(0x606D)
    def _read_velocity_window(self, sub):
        return int(self.velocity_window_rpm)

    @router.writer(0x606D)
    def _write_velocity_window(self, sub, value):
        if int(value) < 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "606Dh は 0 以上")
        self.velocity_window_rpm = float(value)

    @router.reader(0x606F)
    def _read_velocity_threshold(self, sub):
        return int(self.velocity_threshold_rpm)

    @router.writer(0x606F)
    def _write_velocity_threshold(self, sub, value):
        if int(value) < 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "606Fh は 0 以上")
        self.velocity_threshold_rpm = float(value)

    @router.reader(0x6077)
    def _read_torque_actual(self, sub):
        return _clamp_int32(round(self.plant.torque_permille))

    @router.reader(0x6083)
    def _read_profile_acceleration(self, sub):
        return int(self.profile_acceleration_rpm_s)

    @router.writer(0x6083)
    def _write_profile_acceleration(self, sub, value):
        if int(value) <= 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6083h は 1 以上")
        self.profile_acceleration_rpm_s = float(value)

    @router.reader(0x6084)
    def _read_profile_deceleration(self, sub):
        return int(self.profile_deceleration_rpm_s)

    @router.writer(0x6084)
    def _write_profile_deceleration(self, sub, value):
        if int(value) <= 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6084h は 1 以上")
        self.profile_deceleration_rpm_s = float(value)

    @router.reader(0x608F, 1)
    def _read_encoder_increments(self, sub):
        return self.units.encoder_increments

    @router.writer(0x608F, 1)
    def _write_encoder_increments(self, sub, value):
        self.units.set_encoder_resolution(int(value), self.units.motor_revolutions)

    @router.reader(0x608F, 2)
    def _read_encoder_motor_revolutions(self, sub):
        return self.units.motor_revolutions

    @router.writer(0x608F, 2)
    def _write_encoder_motor_revolutions(self, sub, value):
        self.units.set_encoder_resolution(self.units.encoder_increments, int(value))

    @router.reader(0x6091, 1)
    def _read_gear_motor_revolutions(self, sub):
        return self.units.gear_motor_revolutions

    @router.writer(0x6091, 1)
    def _write_gear_motor_revolutions(self, sub, value):
        self.units.set_gear_ratio(int(value), self.units.gear_shaft_revolutions)

    @router.reader(0x6091, 2)
    def _read_gear_shaft_revolutions(self, sub):
        return self.units.gear_shaft_revolutions

    @router.writer(0x6091, 2)
    def _write_gear_shaft_revolutions(self, sub, value):
        self.units.set_gear_ratio(self.units.gear_motor_revolutions, int(value))

    @router.reader(0x60FF)
    def _read_target_velocity(self, sub):
        return _clamp_int32(round(self.target_velocity_rpm))

    @router.writer(0x60FF)
    def _write_target_velocity(self, sub, value):
        self.target_velocity_rpm = float(int(value))

    @router.reader(0x6502)
    def _read_supported_drive_modes(self, sub):
        return SUPPORTED_DRIVE_MODES

    # --- メーカ固有 ---

    @router.writer(0x40C0)
    def _write_alarm_reset(self, sub, value):
        if int(value):
            self.alarms.reset()
            if not self.alarms.is_active:
                self.state_machine.set_fault(False)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_driver_pv.py -v`
Expected: 20 passed

落ちやすい箇所と対処:
- `test_velocity_demand_follows_the_acceleration_ramp` の範囲（40〜60）は 1ms 離散化の丸め次第。実測を出して範囲を狭めるか広げるが、「0.5 秒で目標の半分前後」という性質は崩さない。
- `test_alarm_reset_via_40c0_clears_the_fault` は Fault からの復帰に Controlword bit7 の立ち上がりが必要（Task 13 の仕様）。`40C0h` はアラーム自体を消すだけで、ステートマシンの復帰は `6040h` の Fault reset で行う、という分担になっていることを確認する。

- [ ] **Step 5: 全テストを流してコミット**

Run: `python -m pytest -v`
Expected: すべて passed

```bash
git add omsim/driver/model.py tests/unit/test_driver_pv.py
git commit -m "feat: pv モード (60FFh) と DriverModel へのアラーム連携"
```

---

## Task 19: 複数ノード独立性の結合テスト

**Files:**
- Create: `tests/scenarios/two_nodes_pv.yaml`
- Test: `tests/integration/test_multi_node.py`

**Interfaces:**
- Consumes: `running_sim`, `master`（Task 8 の fixture）、`DriverModel`, `MODE_PV`
- Produces: 設計書 8.1 の 7 項目に対応するテスト

- [ ] **Step 1: 失敗するテストを書く**

`tests/scenarios/two_nodes_pv.yaml`:

```yaml
name: 2 台に別々の速度を与えて独立に追従する
nodes: [1, 2]
steps:
  - nmt: start
  - sdo_write: {index: 0x6060, value: 3}
  - sdo_write: {index: 0x6083, value: 6000}
  - sdo_write: {index: 0x6084, value: 6000}
  - sdo_write: {index: 0x6040, value: 0x0006}
  - sdo_write: {index: 0x6040, value: 0x0007}
  - sdo_write: {index: 0x6040, value: 0x000F}
  - expect: {index: 0x6041, mask: 0x006F, value: 0x0027, timeout: 1.0}
  - sdo_write: {node: 1, index: 0x60FF, value: 100}
  - sdo_write: {node: 2, index: 0x60FF, value: 50}
  - expect: {node: 1, index: 0x606C, value: 100, tolerance: 2, timeout: 3.0}
  - expect: {node: 2, index: 0x606C, value: 50, tolerance: 2, timeout: 3.0}
```

`tests/integration/test_multi_node.py`:

```python
"""設計書 8.1 の複数ノード独立性の検証。"""
import os

import canopen
import pytest

from omsim.apps.scenario import load_scenario, run_scenario
from omsim.driver.model import MODE_PV
from omsim.node.eds import DEFAULT_EDS_PATH

pytestmark = pytest.mark.vcan

SCENARIO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scenarios",
    "two_nodes_pv.yaml",
)


def _enable(model, target_rpm):
    model.write_object(0x6060, 0, MODE_PV)
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    model.write_object(0x6040, 0, 0x0006)
    model.write_object(0x6040, 0, 0x0007)
    model.write_object(0x6040, 0, 0x000F)
    model.write_object(0x60FF, 0, target_rpm)


def test_scenario_two_nodes_reach_different_speeds(running_sim, master):
    scenario = load_scenario(SCENARIO)
    results = run_scenario(scenario, master)
    assert [r for r in results if not r.ok] == []


def test_fault_on_one_node_does_not_stop_the_other(running_sim):
    one = running_sim.models[1]
    two = running_sim.models[2]
    _enable(one, 100)
    _enable(two, 100)
    running_sim.run_for(2.0)

    one.inject_alarm(0x30, 0x2310)
    running_sim.run_for(1.5)

    assert abs(one.read_object(0x606C)) <= 2
    assert abs(two.read_object(0x606C) - 100) <= 2
    assert two.read_object(0x6041) & 0x6F == 0x27


def test_removing_excitation_on_one_node_does_not_affect_the_other(running_sim):
    one = running_sim.models[1]
    two = running_sim.models[2]
    _enable(one, 100)
    _enable(two, 100)
    running_sim.run_for(2.0)

    one.state_machine.voltage_enabled = False  # HWTO 相当。実装は P5
    running_sim.run_for(1.5)

    assert abs(one.read_object(0x606C)) <= 2
    assert abs(two.read_object(0x606C) - 100) <= 2


def test_parameters_do_not_leak_between_nodes(running_sim):
    one = running_sim.models[1]
    two = running_sim.models[2]
    one.write_object(0x6091, 1, 100)
    one.write_object(0x6091, 2, 1)
    assert one.units.gear_ratio == 100.0
    assert two.units.gear_ratio == 1.0


def test_nmt_reset_of_one_node_leaves_the_other_operational(running_sim, master):
    one = running_sim.models[1]
    two = running_sim.models[2]
    _enable(two, 100)
    running_sim.run_for(2.0)

    master.send_message(0x000, bytes([0x81, 1]))  # reset node 1
    running_sim.run_for(0.5)

    assert running_sim.nodes[2].nmt.state != "INITIALISING"
    assert abs(two.read_object(0x606C) - 100) <= 2
    assert one is running_sim.models[1]


def test_sdo_requests_to_both_nodes_are_not_confused(running_sim, master):
    remotes = {}
    for node_id in (1, 2):
        node = canopen.RemoteNode(node_id, DEFAULT_EDS_PATH)
        master.add_node(node)
        node.sdo.RESPONSE_TIMEOUT = 1.0
        remotes[node_id] = node

    remotes[1].sdo[0x6083].raw = 1234
    remotes[2].sdo[0x6083].raw = 4321
    for _ in range(20):
        assert remotes[1].sdo[0x6083].raw == 1234
        assert remotes[2].sdo[0x6083].raw == 4321


def test_emcy_cob_ids_differ_per_node(running_sim):
    assert running_sim.nodes[1].emcy.cob_id == 0x081
    assert running_sim.nodes[2].emcy.cob_id == 0x082
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/integration/test_multi_node.py -v`
Expected: FAIL — `test_scenario_two_nodes_reach_different_speeds` が最初に落ちる（シナリオファイルは作ったが `running_sim` の `run_for` は別スレッドのループと競合する）

`running_sim` fixture は別スレッドで `step()` を回しているため、テストから `running_sim.run_for()` を呼ぶと二重に進む。Task 8 の `conftest.py` に fixture を 1 つ足して解決する:

```python
@pytest.fixture
def stepped_sim(vcan_available):
    """テスト側が明示的に step を進めるシミュレータ（スレッドを使わない）。"""
    network = open_network(channel=vcan_available)
    specs = [
        NodeSpec(node_id=1, eds=DEFAULT_EDS_PATH),
        NodeSpec(node_id=2, eds=DEFAULT_EDS_PATH),
    ]
    manager = NodeManager(specs, network=network, realtime=False)
    manager.start()
    yield manager
    manager.stop()
    close_network(network)
```

`running_sim` を使うのはマスタ側から SDO を投げるテスト（`test_scenario_two_nodes_reach_different_speeds`、`test_sdo_requests_to_both_nodes_are_not_confused`、`test_nmt_reset_of_one_node_leaves_the_other_operational`、`test_emcy_cob_ids_differ_per_node`）。`run_for` を呼ぶテスト（`test_fault_on_one_node_does_not_stop_the_other`、`test_removing_excitation_on_one_node_does_not_affect_the_other`、`test_parameters_do_not_leak_between_nodes`）は `stepped_sim` に差し替える。

`test_nmt_reset_of_one_node_leaves_the_other_operational` は両方が必要なので、`running_sim` を使い `running_sim.run_for` の呼び出しを `time.sleep` に置き換える。

- [ ] **Step 3: conftest に stepped_sim を足し、テストの fixture を振り分ける**

`tests/integration/conftest.py` に上記 `stepped_sim` を追加する。

`tests/integration/test_multi_node.py` の該当テストの引数を `running_sim` から `stepped_sim` に変え、`running_sim.` を `stepped_sim.` に置き換える。`test_nmt_reset_of_one_node_leaves_the_other_operational` は次の形にする:

```python
def test_nmt_reset_of_one_node_leaves_the_other_operational(running_sim, master):
    import time

    one = running_sim.models[1]
    two = running_sim.models[2]
    _enable(two, 100)
    time.sleep(2.0)

    master.send_message(0x000, bytes([0x81, 1]))  # reset node 1
    time.sleep(0.5)

    assert abs(two.read_object(0x606C) - 100) <= 2
    assert one is running_sim.models[1]
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/integration/test_multi_node.py -v`
Expected: 7 passed

Run: `python -m pytest -v`
Expected: すべて passed

シナリオも CLI から流して確認する:

Run: `python -m omsim.apps.scenario tests/scenarios/two_nodes_pv.yaml --junit /tmp/junit.xml`
（別端末で `python -m omsim.apps.omsim_main --node 1 --node 2` を起動しておく）
Expected: 全ステップ `PASS`、終了コード 0

- [ ] **Step 5: コミット**

```bash
git add tests/integration/conftest.py tests/integration/test_multi_node.py tests/scenarios/two_nodes_pv.yaml
git commit -m "test: 複数ノード独立性の検証 (設計書 8.1)"
```

---

## Task 20: pitakuru ノードとの疎通（P1 のマイルストーン）

**Files:**
- Create: `docs/pitakuru-connection.md`
- Create: `scripts/run_with_pitakuru.sh`
- Test: 手動確認（ROS ノードと roscore が絡むため自動化は P7）

**Interfaces:**
- Consumes: `omsim` CLI
- Produces: VM 上で pitakuru の `motor_control_node` が omsim 2 ノードに繋がり、回転指令が通って速度が返る状態と、その再現手順書

pitakuru のノードは `can0` を前提にしている（`src/pitakuru/system/bin/can-start_oriental_motor.sh`）。**pitakuru 側を書き換えず**に繋ぐため、`vcan` インターフェースの名前を `can0` にする。

- [ ] **Step 1: can0 という名前の vcan を作る**

Run（VM 上）:

```bash
sudo modprobe vcan
sudo ip link add dev can0 type vcan
sudo ip link set up can0
ip -o link show can0
```

Expected: `can0: <NOARP,UP,LOWER_UP> mtu 72 ... link/can` の行が出る

すでに実機の `can0` が居る環境では衝突するので、その場合は `vcan0` を作り、pitakuru 側の起動を `--channel vcan0` 相当に読み替える（このタスクでは VM に実機 CAN は無い前提）。

- [ ] **Step 2: omsim を 2 ノードで起動する**

`scripts/run_with_pitakuru.sh`:

```bash
#!/bin/bash
# pitakuru の oriental_motor ノードと繋ぐための omsim 起動。
# pitakuru は can0 / node_id 1,2 / bitrate 500k / reduction 100 を前提にしている
# (src/pitakuru/config/motors/motors_oriental_motor.yaml)。
set -eu
CHANNEL="${1:-can0}"
RECORD="${2:-/tmp/omsim-pitakuru.jsonl}"

python3 -m omsim.apps.omsim_main \
    --channel "$CHANNEL" \
    --eds BLVD-KRD_CANopen_V200.eds \
    --node 1 \
    --node 2 \
    --record "$RECORD"
```

EDS は pitakuru が読んでいる V200 に合わせる。V200 は `pitakuru_ws/src/motors/oriental_motor/data/BLVD-KRD_CANopen_V200.eds` にあるので、`docs/oriental_motor/` にコピーしてから使う:

```bash
cp /home/vagrant/KEISUU/develop/src/motors/oriental_motor/data/BLVD-KRD_CANopen_V200.eds \
   /home/vagrant/KEISUU/omsim/docs/oriental_motor/
cp /home/vagrant/KEISUU/develop/src/motors/oriental_motor/data/BLVD-KBRD_CANopen_V300.eds \
   /home/vagrant/KEISUU/omsim/docs/oriental_motor/
```

Run:

```bash
chmod +x scripts/run_with_pitakuru.sh
./scripts/run_with_pitakuru.sh can0
```

Expected: `omsim: socketcan on can0 nodes=[1, 2]`

- [ ] **Step 3: candump で素の CAN を見ながら pitakuru ノードを起動する**

別端末（VM 上、3 つ使う）:

```bash
# 端末 2
candump -tz can0

# 端末 3
cd /home/vagrant/KEISUU/develop
source devel/setup.bash
roscore &
roslaunch oriental_motor test.launch
```

Expected:
- 端末 2 に `601` / `581`（node1 の SDO）と `602` / `582`（node2 の SDO）の往復が流れる
- pitakuru ノードが `SdoCommunicationError` を出さずに起動を完了する

`601` に対して `581` の応答が abort（データ先頭が `80`）で返る場合は、そのインデックスが V200 の EDS に無いか、omsim が未実装。`80 xx xx xx` の `xx xx` からインデックスを読み、次のどちらかで対処する:
- V200 の EDS に存在するなら omsim にハンドラを追加する（該当オブジェクトの仕様を `HP-5143E.pdf` / `HP-5141J.pdf` で確認）
- 存在しないなら pitakuru 側の想定が古い。abort が正しい挙動なので記録に残す

- [ ] **Step 4: 回転指令が通り速度が返ることを確認する**

pitakuru ノードが速度指令を受ける ROS トピック/サービスを `motor_control_node` から読み取り（`wheel_rpm` 周辺の実装）、指令を出す。

Run（例。実際のトピック名は `rostopic list` で確認する）:

```bash
rostopic list | grep -i motor
rostopic pub -1 <速度指令トピック> <型> <値>
```

Expected:
- `candump` に `60FF`（Target velocity）への SDO 書き込みが流れる
- omsim の記録（`/tmp/omsim-pitakuru.jsonl`）で `actual_velocity_rpm` が指令値に近づく
- pitakuru ノードが `606C`（Velocity actual value）を読んで期待値を得る

記録から確認するコマンド:

```bash
python3 - <<'PY'
import json
last = None
for line in open("/tmp/omsim-pitakuru.jsonl", encoding="utf-8"):
    rec = json.loads(line)
    if rec["kind"] == "state":
        last = rec
print(json.dumps(last["snapshot"], indent=2, ensure_ascii=False))
PY
```

Expected: `nodes` の 1 と 2 それぞれに `state: "operation-enabled"` と 0 でない `actual_velocity_rpm` が出る

- [ ] **Step 5: 手順書に書き起こしてコミット**

`docs/pitakuru-connection.md` に次を書く。**推測ではなく Step 3-4 で実際に観測した内容を書くこと。**

- VM 上での `can0`（vcan）作成手順
- omsim の起動コマンド（使った EDS のバージョンを明記）
- pitakuru 側の起動手順（`roscore` / `roslaunch` の実際に使ったコマンド）
- 実際に流れた CAN フレームの抜粋（`candump -tz can0` の出力を 20 行程度）
- 実際に使った速度指令のトピック名・型・値
- 観測した `actual_velocity_rpm` の値
- abort が返ったオブジェクトの一覧（あれば）と、その対処方針

```bash
git add docs/pitakuru-connection.md scripts/run_with_pitakuru.sh docs/oriental_motor/BLVD-KRD_CANopen_V200.eds docs/oriental_motor/BLVD-KBRD_CANopen_V300.eds
git commit -m "docs: pitakuru oriental_motor ノードとの疎通手順と実測記録"
```

---

## 完了条件

P0-P1 が完了したと言えるのは、次の全部が成立したときだけ。

- [ ] `python3 -m pytest -v` が VM 上で全て passed（SKIP 0 件）
- [ ] `omsim --node 1 --node 2` が vcan0 上で 2 ノードとして応答する
- [ ] `omsim-scenario tests/scenarios/two_nodes_pv.yaml` が全ステップ PASS で終了コード 0
- [ ] 2 台に別々の速度を与えて独立に追従することを結合テストで確認済み
- [ ] 片方を Fault にしても他方が止まらないことを結合テストで確認済み
- [ ] pitakuru の `motor_control_node` を無改造で起動し、回転指令が通って速度が返ることを実機なしで確認済み
- [ ] `docs/pitakuru-connection.md` に実測に基づく手順が書かれている

## 次のフェーズ

P2 以降は設計書 11 節のフェーズ計画に従い、フェーズごとに別の計画を書く。P1 で意図的に後回しにしたもの:

- `6060h` に pv 以外を書くと `NotImplementedError`（P4 で pp / hm / tq）
- `60A8h` / `60A9h` SI unit（P4）
- PDO の送信規則・SYNC・Heartbeat consumer・node guarding・`1003h`（P3）
- HWTO（`voltage_enabled` を外から叩いているだけ。CN4 I/O と動力遮断の実装は P5）
- mxex ローダ（`NodeSpec.mxex` は受け取るが未使用。P5）
- アラーム全コード（P6。今は過負荷 1 件のみ）
- Web 画面（P2）
