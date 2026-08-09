# P2 Web 可視化 + 技術的負債返済 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** シミュレータの状態をブラウザでリアルタイムに見られるようにし、あわせて P0-P1 の最終レビューで指摘された「このまま P3 以降に進むと高くつく」4 件を返済する。

**Architecture:** 前半（Task 1-4）で土台を直す: 層の依存検証を全方向化し、未実装オブジェクトが黙って EDS 既定値を返すのをやめ、pv を運転モードオブジェクトへ分離し、スレッド競合をコマンドキューで解消する。後半（Task 5-11）で FastAPI + WebSocket による可視化を追加する。フロントエンドはビルド不要の単一 HTML + Canvas（VM に Node が無いため）。

**Tech Stack:** Python 3.8 / FastAPI 0.124.4 / uvicorn 0.33.0 / websockets / 素の JavaScript + Canvas / SocketCAN (vcan)

**前提となる文書:**
- 設計書: `docs/superpowers/specs/2026-08-08-oriental-motor-simulator-design.md`（7 節が Web 画面、9 節がエラー処理）
- P0-P1 計画: `docs/superpowers/plans/2026-08-08-oriental-motor-simulator-p0-p1.md`
- 進捗台帳: `.git/sdd/progress.md`

## Global Constraints

- Python は **3.8**（Vagrant VM の Ubuntu 20.04）。3.9 以降の構文（`list[int]` の実行時評価、`dict | dict`、`match`、walrus 以降の新構文）を使わない。型注釈は `typing` から import する。
- 依存は完全に pin する: `canopen==2.4.1` / `python-can==4.5.0` / `pytest==8.3.5` / `PyYAML==6.0.2` / `fastapi==0.124.4` / `uvicorn==0.33.0`
- **`omsim/driver/` 配下は `can` と `canopen` を import してはならない。** さらに Task 1 以降は層の依存規則全体が自動検証される。
- **複数ノードを 1 プロセスで同時に動かす。** `DriverModel` はインスタンスごとに完全独立な状態を持ち、クラス変数やモジュールグローバルで状態を共有しない。`ObjectRouter` は状態を持ってはならない（表のみ）。
- シミュレーションのステップは **1ms 固定**（`SimClock.STEP_SECONDS = 0.001`）。
- **未実装の挙動を黙って既定値で答えない。** 設計書 9 節: 「シミュレータ自身の内部不整合は即座に落とす。黙って続行して嘘の合格を出すのが最悪」。未実装は `omsim --list-stubs` に必ず現れること。
- **git commit に Claude / AI の署名や言及を一切入れない。コミットメッセージは日本語で書く。** 必要なら `git -c user.name="Kousuke Takeuchi" commit ...`。
- ファイルは改行 **LF** で保存する。
- **VM の共有フォルダ経由でファイルを保存する。scp で VM に直接置かない。**
- **`pitakuru_ws` リポジトリには書き込まない。**

## 実行環境

リポジトリ: `C:\Users\ktake\code\keisuu\oriental_motor_simulator`（Windows 側で編集と git）
テスト実行は Vagrant VM（`/home/vagrant/KEISUU/omsim` にマウント済み）:

```bash
cd /c/Users/ktake/code/keisuu/oriental_motor_simulator && ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q"
```

- `vcan0` が無ければ `bash scripts/setup_vcan.sh vcan0`
- `ssh` 経由のバックグラウンド起動がハングしたら `rtk proxy ssh ...` を使う
- コンソールスクリプト `omsim` はログインシェルでのみ PATH に入る。非対話では `python3 -m omsim.apps.omsim_main` を使う
- 開始時点で **206 テスト passed**

---

## ファイル構成

| ファイル | 責務 | 状態 |
|---|---|---|
| `tests/unit/test_layering.py` | 層の依存規則を全方向・再帰的に検証 | 書き換え |
| `omsim/driver/objects.py` | `ObjectRouter`。未登録は abort、`passthrough` を追加 | 変更 |
| `omsim/driver/model.py` | `DriverModel`。運転モードを委譲する形に縮小 | 変更 |
| `omsim/driver/operation.py` | `OperationMode` 基底と `ProfileVelocityMode` | 新規 |
| `omsim/driver/coverage.py` | EDS と実装の突き合わせ（網羅率レポート） | 新規 |
| `omsim/sim/manager.py` | `NodeManager`。コマンドキューの適用点 | 変更 |
| `omsim/node/od_bridge.py` | コールバックはキューに積むだけに変更 | 変更 |
| `omsim/sim/command_queue.py` | スレッド境界を越える書込みコマンドのキュー | 新規 |
| `omsim/web/__init__.py` | パッケージ | 新規 |
| `omsim/web/hub.py` | `SnapshotHub`。状態と CAN ログの購読・配信 | 新規 |
| `omsim/web/app.py` | FastAPI アプリ（静的配信 / REST / WebSocket） | 新規 |
| `omsim/web/static/index.html` | 単一ページ（3 ペイン） | 新規 |
| `omsim/web/static/app.js` | WebSocket 受信と描画 | 新規 |
| `omsim/web/static/style.css` | スタイル | 新規 |
| `omsim/apps/omsim_main.py` | `--web-port` を追加 | 変更 |
| `requirements.txt` | fastapi / uvicorn を pin | 変更 |

---

## Task 1: 層の依存規則を全方向で検証する

**Files:**
- Modify: `tests/unit/test_layering.py`（全面書き換え）

**Interfaces:**
- Consumes: なし
- Produces: なし（テストのみ）。以降の全タスクがこの規則に縛られる

現在の `test_layering.py` は `omsim/driver/` 直下の `.py` だけを非再帰で見て、`can` / `canopen` の import しか検出しません。Task 3 で `omsim/driver/operation.py` が増え、Task 5-7 で `omsim/web/` が増えるため、**先に検証を全方向化します。**

許可する依存（上から下への一方向のみ）:

```
apps  →  web, sim, node, can, driver
web   →  sim, driver
sim   →  node, can, driver
node  →  driver          (+ canopen は node のみ許可)
can   →  (なし)          (+ canopen は can のみ許可)
driver→  (なし)
```

`omsim/driver/` は他のどの omsim パッケージにも依存してはいけません（`omsim.driver.*` 同士は可）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_layering.py`（全面置き換え）:

```python
"""omsim パッケージ間の依存規則を検証する。

driver 層が can/canopen や上位層に依存すると、CAN 抜きでドライバ挙動を
単体テストできなくなる。規則を 1 箇所で表にして全方向を検査する。
"""
import ast
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OMSIM_ROOT = os.path.join(REPO_ROOT, "omsim")

# パッケージ -> import してよい omsim サブパッケージ
ALLOWED_INTERNAL = {
    "driver": set(),
    "can": set(),
    "node": {"driver"},
    "sim": {"driver", "node", "can"},
    "web": {"driver", "sim"},
    "apps": {"driver", "node", "can", "sim", "web"},
}

# CAN ライブラリを import してよいパッケージ
ALLOWED_CAN_LIBS = {"can", "node", "sim", "apps"}
CAN_LIBS = {"can", "canopen"}


def _iter_modules():
    for dirpath, dirnames, filenames in os.walk(OMSIM_ROOT):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, OMSIM_ROOT).replace(os.sep, "/")
            package = rel.split("/")[0] if "/" in rel else ""
            yield package, rel, path


def _imported_roots(path):
    """そのファイルが import しているトップレベル名の集合を返す。"""
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
                roots.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 相対 import は同一パッケージ内なので対象外
                continue
            if node.module:
                roots.add(node.module.split(".")[0])
                roots.add(node.module)
    return roots


def _omsim_subpackages(roots):
    found = set()
    for name in roots:
        if name.startswith("omsim."):
            parts = name.split(".")
            if len(parts) >= 2:
                found.add(parts[1])
    return found


def test_every_package_is_covered_by_the_rule_table():
    packages = set(
        package for package, _rel, _path in _iter_modules() if package
    )
    missing = packages - set(ALLOWED_INTERNAL)
    assert missing == set(), "依存規則表に無いパッケージ: {}".format(sorted(missing))


def test_internal_dependencies_follow_the_rule_table():
    offenders = []
    for package, rel, path in _iter_modules():
        if not package:
            continue
        allowed = ALLOWED_INTERNAL[package] | {package}
        for used in _omsim_subpackages(_imported_roots(path)):
            if used not in allowed:
                offenders.append("{} -> omsim.{}".format(rel, used))
    assert offenders == [], "層の依存規則違反: {}".format(offenders)


def test_can_libraries_are_confined_to_the_allowed_packages():
    offenders = []
    for package, rel, path in _iter_modules():
        if package in ALLOWED_CAN_LIBS:
            continue
        used = _imported_roots(path) & CAN_LIBS
        if used:
            offenders.append("{} -> {}".format(rel, sorted(used)))
    assert offenders == [], "can/canopen を import してはいけない層: {}".format(offenders)


def test_driver_layer_imports_no_other_omsim_package():
    offenders = []
    for package, rel, path in _iter_modules():
        if package != "driver":
            continue
        used = _omsim_subpackages(_imported_roots(path)) - {"driver"}
        if used:
            offenders.append("{} -> {}".format(rel, sorted(used)))
    assert offenders == [], "driver 層が他パッケージに依存: {}".format(offenders)


def test_the_check_actually_detects_a_violation(tmp_path):
    """検査自体が空振りしていないことを確認する。"""
    bad = os.path.join(str(tmp_path), "bad.py")
    with open(bad, "w", encoding="utf-8") as handle:
        handle.write("import canopen\nfrom omsim.sim import manager\n")
    roots = _imported_roots(bad)
    assert "canopen" in roots
    assert _omsim_subpackages(roots) == {"sim"}
```

- [ ] **Step 2: テストを実行して現状を確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_layering.py -v"`
Expected: 5 件すべて PASS（現在のコードは規則を守っているはず）。**もし落ちたら、それは実在する層違反なので報告書に記録し、規則表ではなくコードを直すこと。**

- [ ] **Step 3: 検査が本当に効くことを手で確かめる**

一時的に `omsim/driver/model.py` の先頭に `import canopen` を足して実行する:

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_layering.py -q"`
Expected: `test_can_libraries_are_confined_to_the_allowed_packages` と `test_driver_layer_imports_no_other_omsim_package` が FAIL

**確認したら必ず `import canopen` を消して、再度 5 件 PASS に戻すこと。** この確認の実測出力を報告書に残す。

- [ ] **Step 4: 全テストを実行**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q"`
Expected: 206 件から 4 件増えて 210 passed（旧 `test_layering.py` の 1 件が 5 件になるため）

- [ ] **Step 5: コミット**

```bash
git add tests/unit/test_layering.py
git commit -m "test: 層の依存規則を全方向・再帰的に検証する"
```

---

## Task 2: 未実装オブジェクトが黙って EDS 既定値を返すのをやめる

**Files:**
- Modify: `omsim/driver/objects.py`
- Modify: `omsim/driver/model.py`
- Create: `omsim/driver/coverage.py`
- Modify: `omsim/apps/omsim_main.py`
- Test: `tests/unit/test_object_router.py`（追記）
- Test: `tests/unit/test_coverage.py`（新規）

**Interfaces:**
- Consumes: `ObjectRouter`、`ObjectAccessError`、`ABORT_NOT_IN_OD = 0x06020000`
- Produces:
  - `ObjectRouter.read(owner, index, sub)` は未登録なら `ObjectAccessError(ABORT_NOT_IN_OD)` を投げる（従来は `None`）
  - `ObjectRouter.passthrough(index, sub=0, reason="")` — 「値を保持して読み返せるが、挙動には効かない」オブジェクトを登録する。同時にスタブとして記録される
  - `DriverModel.passthrough_values: Dict[Tuple[int, int], int]` — passthrough で書かれた値
  - `omsim/driver/coverage.py`: `coverage_report(od, router) -> Dict[str, Any]`
    キー: `total`(int) / `implemented`(int) / `passthrough`(int) / `unimplemented`(int) / `unimplemented_list`(List[Tuple[int,int]])
  - `omsim --coverage` で網羅率を出力して終了

### なぜこれをやるか

EDS V400 のオブジェクトは **289 件**、`model.py` の router 登録は **47 件**です。`ObjectRouter.read` が未登録で `None` を返し、`canopen.LocalNode.get_data()` がそれを EDS の `default` にフォールスルーするため、**残り 240 件超は SDO で読むとエラーも警告も出さずに「それらしい値」が返ります。**

被試験プログラムが `6071h`（Target torque）や `607Ah`（Target position）を読むと動いてしまい、実機では違う値になります。設計書 9 節「未定義オブジェクトへのアクセス → 仕様通り SDO abort」に反しており、このプロジェクトが最も嫌う「嘘の合格」そのものです。

ただし、**EDS の既定値を返すのが正しいオブジェクトもあります。** MEXE02 の `.mxex` に保存される純パラメータ群がそれで、これらは「値を保持して読み返せる」ことに意味があります。これらは `passthrough` として**明示的に列挙**し、同時にスタブ一覧にも出します（挙動には効かないため）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_object_router.py` に追記します。

**先に既存の `test_unregistered_read_returns_none` を削除してください。** このテストは「未登録の読みは `None` を返す」という、今から変える仕様そのものを固定しています。同じファイル内で新旧の仕様が矛盾するため、置き換えが必要です（テストを消すのはこの 1 件だけで、他は消さないこと）。

そのうえで末尾に追記:

```python
from omsim.driver.errors import ABORT_NOT_IN_OD


class WithPassthrough(object):
    router = ObjectRouter()

    def __init__(self):
        self.passthrough_values = {}

    router.passthrough(0x414B, 0, "P5: ATL 機能は未実装。値の保持のみ")


def test_unregistered_read_now_aborts_instead_of_returning_none():
    with pytest.raises(ObjectAccessError) as exc:
        Fake.router.read(Fake(), 0x1008, 0)
    assert exc.value.abort_code == ABORT_NOT_IN_OD


def test_passthrough_read_returns_none_until_written():
    owner = WithPassthrough()
    assert WithPassthrough.router.read(owner, 0x414B, 0) is None


def test_passthrough_stores_and_reads_back():
    owner = WithPassthrough()
    WithPassthrough.router.write(owner, 0x414B, 0, 7)
    assert WithPassthrough.router.read(owner, 0x414B, 0) == 7


def test_passthrough_is_listed_as_a_stub():
    entries = [(i, s) for i, s, _r in WithPassthrough.router.stubs()]
    assert (0x414B, 0) in entries


def test_passthrough_values_are_per_instance():
    a, b = WithPassthrough(), WithPassthrough()
    WithPassthrough.router.write(a, 0x414B, 0, 7)
    assert WithPassthrough.router.read(b, 0x414B, 0) is None
```

`tests/unit/test_coverage.py`（新規）:

```python
from omsim.driver.coverage import coverage_report
from omsim.driver.model import DriverModel
from omsim.node.eds import DEFAULT_EDS_PATH, load_eds


def test_report_counts_every_eds_object():
    od = load_eds(DEFAULT_EDS_PATH)
    report = coverage_report(od, DriverModel.router)
    assert report["total"] > 200
    assert report["implemented"] + report["passthrough"] + report["unimplemented"] == report["total"]


def test_known_implemented_object_is_counted_as_implemented():
    od = load_eds(DEFAULT_EDS_PATH)
    report = coverage_report(od, DriverModel.router)
    assert (0x6041, 0) not in report["unimplemented_list"]


def test_known_unimplemented_object_is_listed():
    od = load_eds(DEFAULT_EDS_PATH)
    report = coverage_report(od, DriverModel.router)
    # 607Ah Target position は P4 (pp モード) まで未実装
    assert (0x607A, 0) in report["unimplemented_list"]


def test_unimplemented_list_is_sorted():
    od = load_eds(DEFAULT_EDS_PATH)
    report = coverage_report(od, DriverModel.router)
    assert report["unimplemented_list"] == sorted(report["unimplemented_list"])
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_object_router.py tests/unit/test_coverage.py -q 2>&1 | tail -20"`
Expected: FAIL（`passthrough` が無い、`coverage` モジュールが無い、未登録 read が `None` を返す）

- [ ] **Step 3: `ObjectRouter` を変更する**

`omsim/driver/objects.py` の `read` を変更し、`passthrough` を追加する:

```python
from omsim.driver.errors import (
    ABORT_NOT_IN_OD,
    ABORT_NOT_WRITABLE,
    ObjectAccessError,
)
```

`__init__` に 1 行追加:

```python
        self._passthrough = set()
```

`passthrough` メソッドを追加（`mark_stub` の下）:

```python
    def passthrough(self, index, sub=0, reason=""):
        """値を保持して読み返せるが、挙動には一切効かないオブジェクトを登録する。

        MEXE02 の .mxex に保存される純パラメータ群のように、「読み書きできる
        こと自体に意味がある」オブジェクトのための口。書かれるまでは None を
        返して EDS の既定値へフォールスルーし、書かれた後はその値を返す。

        挙動に効かない以上これは未実装であり、必ずスタブ一覧にも載せる。
        """
        key = (index, sub)
        self._passthrough.add(key)
        self._readers[key] = _passthrough_reader(key)
        self._writers[key] = _passthrough_writer(key)
        self._stubs[key] = reason

    def implemented_keys(self):
        """reader または writer が登録されている (index, sub) の集合。"""
        return set(self._readers) | set(self._writers)

    def passthrough_keys(self):
        return set(self._passthrough)
```

`read` を変更:

```python
    def read(self, owner, index, sub):
        func = self._readers.get((index, sub))
        if func is None:
            raise ObjectAccessError(
                ABORT_NOT_IN_OD,
                "{:04X}h:{:02X} は未実装です (omsim --coverage で一覧)".format(index, sub),
            )
        return func(owner, sub)
```

モジュール末尾にヘルパーを追加:

```python
def _passthrough_reader(key):
    def read(owner, sub):
        return owner.passthrough_values.get(key)

    return read


def _passthrough_writer(key):
    def write(owner, sub, value):
        owner.passthrough_values[key] = int(value)

    return write
```

- [ ] **Step 4: `DriverModel` に passthrough を登録する**

`omsim/driver/model.py` の `__init__` に追加:

```python
        # passthrough で書かれた値。インスタンスごとに独立。
        self.passthrough_values = {}
```

クラス本体の末尾（メーカ固有ハンドラの後）に、`.mxex` に保存される純パラメータ群を登録する:

```python
    # --- .mxex に保存される純パラメータ群 ---
    # 値を保持して読み返せるが、挙動には効かない。実装フェーズは各行のとおり。
    # netid == index - 0x4000 で mxex と対応する (設計書 2.3)。
    _PASSTHROUGH_PARAMETERS = (
        (0x4148, "P5: 絶対座標未設定時の絶対位置決め許可。値の保持のみ"),
        (0x414B, "P5: ATL 機能モード設定。値の保持のみ"),
        (0x415F, "P5: JOG/HOME トルク制限値。値の保持のみ"),
        (0x4160, "P5: (HOME) 原点復帰モード。値の保持のみ"),
        (0x4163, "P5: (HOME) 起動速度。値の保持のみ"),
        (0x4169, "P5: (HOME) 2 センサ原点復帰の戻りステップ数。値の保持のみ"),
        (0x4186, "P6: アラーム発生時の停止タイムアウト。値の保持のみ"),
        (0x41A4, "P5: モーター回転方向。値の保持のみ"),
        (0x41CA, "P5: WRAP 設定。値の保持のみ"),
        (0x4735, "P4: カスタム停止レート。値の保持のみ"),
        (0x4736, "P4: カスタム停止時間。値の保持のみ"),
    )

    for _index, _reason in _PASSTHROUGH_PARAMETERS:
        router.passthrough(_index, 0, _reason)
    del _index, _reason
```

- [ ] **Step 5: `coverage.py` を書く**

`omsim/driver/coverage.py`:

```python
"""EDS に載るオブジェクトと、実装済みオブジェクトを突き合わせる。

「何を実装したか」ではなく「何がまだ実装されていないか」を機械的に出せる
ようにするためのモジュール。設計書 9 節の「未実装オブジェクトの一覧を
コマンドで出せるようにし、網羅の進捗を可視化する」に対応する。

canopen に依存しないよう、OD は「index -> オブジェクト」のマッピングと
して扱い、サブインデックスの有無はダックタイピングで判定する。
"""


def _iter_od_keys(od):
    """OD に含まれる (index, sub) を列挙する。"""
    for index in sorted(od):
        obj = od[index]
        subs = getattr(obj, "subindices", None)
        if subs:
            for sub in sorted(subs):
                yield (index, sub)
        else:
            yield (index, 0)


def coverage_report(od, router):
    implemented = router.implemented_keys()
    passthrough = router.passthrough_keys()

    total = 0
    implemented_count = 0
    passthrough_count = 0
    unimplemented = []
    for key in _iter_od_keys(od):
        total += 1
        if key in passthrough:
            passthrough_count += 1
        elif key in implemented:
            implemented_count += 1
        else:
            unimplemented.append(key)

    return {
        "total": total,
        "implemented": implemented_count,
        "passthrough": passthrough_count,
        "unimplemented": len(unimplemented),
        "unimplemented_list": sorted(unimplemented),
    }


def format_report(report):
    lines = [
        "EDS オブジェクト総数: {}".format(report["total"]),
        "  実装済み          : {}".format(report["implemented"]),
        "  値の保持のみ      : {}".format(report["passthrough"]),
        "  未実装            : {}".format(report["unimplemented"]),
        "",
        "未実装の一覧:",
    ]
    for index, sub in report["unimplemented_list"]:
        lines.append("  {:04X}h:{:02X}".format(index, sub))
    return "\n".join(lines)
```

- [ ] **Step 6: `--coverage` を CLI に足す**

`omsim/apps/omsim_main.py` の `parse_args` に追加（`--list-stubs` の隣）:

```python
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="EDS に対する実装網羅率と未実装オブジェクト一覧を出力して終了する",
    )
```

`main()` の先頭側、`--list-stubs` の処理の隣に追加:

```python
    if args.coverage:
        from omsim.driver.coverage import coverage_report, format_report
        from omsim.driver.model import DriverModel
        from omsim.node.eds import load_eds

        print(format_report(coverage_report(load_eds(args.eds), DriverModel.router)))
        return 0
```

- [ ] **Step 7: テストを通し、既存の落ちたテストを判断する**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -30"`

**既存テストが落ちます。** 落ちたものを 1 件ずつ次の基準で判断してください:

- **「未登録オブジェクトが `None` を返す」ことに依存していたテスト** → 新しい仕様（abort）に合わせて修正する。修正内容を報告書に書く
- **`tests/scenarios/sdo_smoke.yaml` が `414Bh` / `4186h` の EDS 既定値を読んでいる** → これらは passthrough に登録済みなので、書かれる前は `None` を返して EDS 既定値にフォールスルーし、従来どおり通るはず。通らなければ passthrough の実装が誤っている
- **`tests/unit/test_od_bridge.py` の `test_falls_through_to_eds_default_when_driver_returns_none`** → passthrough オブジェクト（`414Bh`）を使う形に書き換える。「driver が `None` を返したら EDS 既定値」という仕組み自体は残すべき仕様なので、テストは消さないこと
- **pitakuru ノードが読むオブジェクトが abort されるようになった** → それは正しい挙動。`docs/pitakuru-connection.md` の abort 一覧に追記する

**判断に迷ったら `BLOCKED` で報告してください。** テストを消して通すのは禁止です。

- [ ] **Step 8: 網羅率を実測して記録し、コミット**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m omsim.apps.omsim_main --coverage | head -20"`
Expected: 総数・実装済み・値の保持のみ・未実装の件数と、未実装の一覧が出る

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -2"`
Expected: 全 passed

```bash
git add omsim/driver/objects.py omsim/driver/model.py omsim/driver/coverage.py omsim/apps/omsim_main.py tests/unit/test_object_router.py tests/unit/test_coverage.py
git commit -m "fix: 未実装オブジェクトが EDS 既定値を黙って返すのをやめ、網羅率を可視化する"
```

---

## Task 3: pv モードを運転モードオブジェクトへ分離する

**Files:**
- Create: `omsim/driver/operation.py`
- Modify: `omsim/driver/model.py`
- Test: `tests/unit/test_operation_pv.py`（新規）

**Interfaces:**
- Consumes: `Cia402StateMachine`、`TrapezoidProfile`、`MotorPlant`、`UnitConverter`
- Produces:
  - `OperationMode` — 基底クラス。`mode_code` プロパティ（int）、`step(dt, ctx)`、`apply_status_bits(ctx)`
  - `ProfileVelocityMode(OperationMode)` — `mode_code == 3`
  - `OperationContext` — `collections.namedtuple("OperationContext", ["state_machine", "profile", "plant", "units", "params"])`
  - `DriverModel.operation: OperationMode`
  - `MODE_PV` は `omsim/driver/model.py` に残す（既存 import 互換のため）

### なぜこれをやるか

pv のロジックが `DriverModel.step()` に直書きされており、`model.py` は 447 行で driver 層最大です。P4 で pp / hm / tq を足すと `step()` が 4 モード分の分岐の塊になり、Statusword bit10/12/13 のモード別意味づけも同じ関数に混ざります。**今なら分離コストは小さく、P4 で払うより安い**です。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_operation_pv.py`:

```python
import pytest

from omsim.driver.motor_plant import MotorPlant
from omsim.driver.operation import (
    OperationContext,
    OperationMode,
    ProfileVelocityMode,
)
from omsim.driver.profile import TrapezoidProfile
from omsim.driver.state_machine import Cia402StateMachine
from omsim.driver.units import UnitConverter


class Params(object):
    def __init__(self):
        self.target_velocity_rpm = 0.0
        self.profile_acceleration_rpm_s = 1000.0
        self.profile_deceleration_rpm_s = 1000.0
        self.velocity_window_rpm = 1.0
        self.velocity_threshold_rpm = 1.0


def make_context():
    return OperationContext(
        state_machine=Cia402StateMachine(),
        profile=TrapezoidProfile(),
        plant=MotorPlant(),
        units=UnitConverter(),
        params=Params(),
    )


def enable(ctx):
    ctx.state_machine.step(0.001)
    ctx.state_machine.write_controlword(0x0006)
    ctx.state_machine.write_controlword(0x0007)
    ctx.state_machine.write_controlword(0x000F)
    ctx.plant.excited = True


def test_pv_mode_code_is_three():
    assert ProfileVelocityMode().mode_code == 3


def test_base_class_requires_subclasses_to_implement_step():
    ctx = make_context()
    with pytest.raises(NotImplementedError):
        OperationMode().step(0.001, ctx)


def test_pv_drives_the_profile_towards_the_target():
    ctx = make_context()
    enable(ctx)
    mode = ProfileVelocityMode()
    ctx.params.target_velocity_rpm = 100.0
    ctx.params.profile_acceleration_rpm_s = 6000.0
    for _ in range(3000):
        mode.step(0.001, ctx)
    assert abs(ctx.units.internal_to_rpm(ctx.plant.velocity) - 100.0) <= 1.0


def test_pv_holds_zero_while_not_excited():
    ctx = make_context()
    mode = ProfileVelocityMode()
    ctx.params.target_velocity_rpm = 100.0
    for _ in range(1000):
        mode.step(0.001, ctx)
    assert ctx.plant.velocity == 0.0


def test_pv_sets_target_reached_when_settled():
    ctx = make_context()
    enable(ctx)
    mode = ProfileVelocityMode()
    ctx.params.target_velocity_rpm = 100.0
    ctx.params.profile_acceleration_rpm_s = 6000.0
    ctx.params.profile_deceleration_rpm_s = 6000.0
    ctx.params.velocity_window_rpm = 2.0
    for _ in range(3000):
        mode.step(0.001, ctx)
        mode.apply_status_bits(ctx)
    assert ctx.state_machine.target_reached is True


def test_pv_sets_bit12_when_stopped():
    ctx = make_context()
    enable(ctx)
    mode = ProfileVelocityMode()
    ctx.params.target_velocity_rpm = 0.0
    mode.step(0.001, ctx)
    mode.apply_status_bits(ctx)
    assert ctx.state_machine.operation_mode_specific_12 is True


def test_pv_clears_bit12_while_running():
    ctx = make_context()
    enable(ctx)
    mode = ProfileVelocityMode()
    ctx.params.target_velocity_rpm = 100.0
    ctx.params.profile_acceleration_rpm_s = 6000.0
    for _ in range(3000):
        mode.step(0.001, ctx)
        mode.apply_status_bits(ctx)
    assert ctx.state_machine.operation_mode_specific_12 is False


def test_two_modes_do_not_share_state():
    a, b = ProfileVelocityMode(), ProfileVelocityMode()
    assert a is not b
    assert a.mode_code == b.mode_code
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_operation_pv.py -q 2>&1 | tail -10"`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.driver.operation'`

- [ ] **Step 3: `operation.py` を書く**

`omsim/driver/operation.py`:

```python
"""運転モード。CiA402 の Modes of operation (6060h) ごとの振る舞いを持つ。

DriverModel は「どのモードか」を選ぶだけにして、モードごとの制御則と
Statusword のモード固有ビット (bit10/12/13) の意味づけをここに閉じ込める。
P4 で pp / hm / tq を足すときは、このクラスを増やすだけで済む形にしてある。

参照: HP-5143E 7 章 (Operation mode)
"""
import collections

OperationContext = collections.namedtuple(
    "OperationContext", ["state_machine", "profile", "plant", "units", "params"]
)


class OperationMode(object):
    """運転モードの基底。"""

    @property
    def mode_code(self):
        """6060h / 6061h に載るモード番号。"""
        raise NotImplementedError("mode_code はサブクラスが実装する")

    def step(self, dt, ctx):
        """1 ステップぶん、指令を生成してプラントを進める。"""
        raise NotImplementedError("step はサブクラスが実装する")

    def apply_status_bits(self, ctx):
        """Statusword のモード固有ビットを更新する。"""
        raise NotImplementedError("apply_status_bits はサブクラスが実装する")


class ProfileVelocityMode(OperationMode):
    """Profile Velocity Mode (pv)。HP-5143E 7.2 (p37)。"""

    MODE_CODE = 3

    @property
    def mode_code(self):
        return self.MODE_CODE

    def step(self, dt, ctx):
        params = ctx.params
        ctx.profile.acceleration = ctx.units.rpm_to_internal(
            params.profile_acceleration_rpm_s)
        ctx.profile.deceleration = ctx.units.rpm_to_internal(
            params.profile_deceleration_rpm_s)

        if ctx.plant.excited:
            ctx.profile.set_target(ctx.units.rpm_to_internal(params.target_velocity_rpm))
        else:
            ctx.profile.set_target(0.0)

        ctx.profile.step(dt)
        ctx.plant.step(dt, ctx.profile.command)

    def apply_status_bits(self, ctx):
        params = ctx.params
        actual_rpm = ctx.units.internal_to_rpm(ctx.plant.velocity)
        command_rpm = ctx.units.internal_to_rpm(ctx.profile.command)

        ctx.state_machine.target_reached = (
            ctx.plant.excited
            and ctx.profile.at_target
            and abs(actual_rpm - command_rpm) <= params.velocity_window_rpm
        )
        # HP-5143E 7.2.4 (p39): pv の bit12 (SPD) は「速度が 0 かどうか」。
        ctx.state_machine.operation_mode_specific_12 = (
            abs(actual_rpm) <= params.velocity_threshold_rpm
        )
```

- [ ] **Step 4: `DriverModel` を委譲する形に変える**

`omsim/driver/model.py`:

1. import を追加:

```python
from omsim.driver.operation import OperationContext, ProfileVelocityMode
```

2. `__init__` に追加:

```python
        self.operation = ProfileVelocityMode()
```

3. `MODE_PV` の定義は `ProfileVelocityMode.MODE_CODE` を参照する形にする:

```python
MODE_PV = ProfileVelocityMode.MODE_CODE
```

4. `step(dt)` の中の「加減速レート換算 → 目標設定 → プロファイル進行 → プラント進行 → target reached → bit12」の部分を、モードへの委譲に置き換える:

```python
    def _context(self):
        return OperationContext(
            state_machine=self.state_machine,
            profile=self.profile,
            plant=self.plant,
            units=self.units,
            params=self,
        )

    def step(self, dt):
        self.sim_time += dt

        if self.alarms.is_active:
            self.state_machine.set_fault(True)
        self.state_machine.step(dt)

        self._sync_excited()

        ctx = self._context()
        self.operation.step(dt, ctx)

        if not self.state_machine.is_operation_enabled and self.state_machine.state in (
            State.FAULT, State.SWITCH_ON_DISABLED
        ):
            self.profile.reset(0.0)

        self.operation.apply_status_bits(ctx)

        # HP-5143E 6.2 (p35) Transition 12: quick-stop-active は減速完了で
        # switch-on-disabled へ抜ける。605Ah は未実装 (P5)。
        if self.state_machine.state == State.QUICK_STOP_ACTIVE:
            stopped = (
                self.profile.command == 0.0
                and abs(self.actual_velocity_rpm) <= self.velocity_threshold_rpm
            )
            if stopped:
                self.state_machine.stop_completed()
```

`params=self` としているのは、`DriverModel` が `target_velocity_rpm` / `profile_acceleration_rpm_s` / `profile_deceleration_rpm_s` / `velocity_window_rpm` / `velocity_threshold_rpm` をそのまま属性として持っているためです。

5. `_write_mode`（`6060h` の writer）を、モードオブジェクトの差し替えに変える:

```python
    @router.writer(0x6060)
    def _write_mode(self, sub, value):
        mode = int(value)
        if mode != MODE_PV:
            raise NotImplementedObjectError(
                ABORT_DEVICE_STATE,
                "運転モード {} は P4 で実装する (6060h)".format(mode),
            )
        self.mode = mode
        self.operation = ProfileVelocityMode()
```

（`NotImplementedObjectError` と `ABORT_DEVICE_STATE` は既に `omsim/driver/errors.py` にあります。既存の import 行に合わせてください。）

- [ ] **Step 5: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_operation_pv.py -v"`
Expected: 8 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed。**既存の `tests/unit/test_driver_pv.py` の 20 件超が 1 件も落ちないこと**（挙動は変えていないため）。落ちたら挙動が変わっているので原因を報告書に書くこと

- [ ] **Step 6: `model.py` が小さくなったことを確認してコミット**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && wc -l omsim/driver/model.py omsim/driver/operation.py"`

行数を報告書に記録する。

```bash
git add omsim/driver/operation.py omsim/driver/model.py tests/unit/test_operation_pv.py
git commit -m "refactor: pv を OperationMode へ分離し DriverModel を組み立て役に戻す"
```

---

## Task 4: スレッド境界をコマンドキューで解消する

**Files:**
- Create: `omsim/sim/command_queue.py`
- Modify: `omsim/node/od_bridge.py`
- Modify: `omsim/sim/manager.py`
- Test: `tests/unit/test_command_queue.py`（新規）
- Test: `tests/integration/test_sdo_over_vcan.py`（追記）

**Interfaces:**
- Consumes: `DriverModel.write_object(index, sub, value)`
- Produces:
  - `CommandQueue()` — `put(index, sub, value)` / `drain(model)` / `pending_count()`
  - `build_local_node(node_id, od, model, queue=None)` — `queue` を渡すと write コールバックはキューに積むだけになる
  - `NodeManager` は各ノードの `CommandQueue` を持ち、`step()` の**先頭**で `drain` する

### なぜこれをやるか

現在、CAN 受信は python-can の Notifier スレッドで動き、シミュレーションループは別スレッド（または主スレッド）で動きます。**同一の `DriverModel` に対して `step()` と `write_object()` が並行に走ります。**

今は GIL と単純代入に救われているだけです。`write_controlword` は状態機械の read-modify-write + `_sync_excited()` で、`step()` の途中に割り込むと励磁と状態が食い違った瞬間が観測されえます。**P3 で PDO / SYNC / Heartbeat が入ると送信側もスレッドを持つため、再現しない間欠バグに化けます。**

実機のドライバは「受信したコマンドを次の制御周期の先頭で適用する」動作なので、**キュー化は仕様的にも正しい**です。

**読み出し（`read_object`）はキューを通しません。** 読みは副作用が無く、1ms 待たせると SDO のタイムアウトを招くためです。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_command_queue.py`:

```python
import threading

from omsim.driver.model import DriverModel
from omsim.sim.command_queue import CommandQueue


def test_starts_empty():
    assert CommandQueue().pending_count() == 0


def test_put_does_not_apply_immediately():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 1234)
    assert model.read_object(0x6083) != 1234
    assert queue.pending_count() == 1


def test_drain_applies_in_order():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 100)
    queue.put(0x6083, 0, 200)
    queue.drain(model)
    assert model.read_object(0x6083) == 200
    assert queue.pending_count() == 0


def test_drain_on_empty_queue_is_a_no_op():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.drain(model)
    assert queue.pending_count() == 0


def test_drain_reports_errors_without_losing_later_commands():
    """不正な書き込みがあっても後続のコマンドは適用される。"""
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 0)      # 0 は範囲外 (1 以上)
    queue.put(0x6083, 0, 500)
    errors = queue.drain(model)
    assert len(errors) == 1
    assert model.read_object(0x6083) == 500


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

    assert queue.pending_count() == 800
    queue.drain(model)
    assert queue.pending_count() == 0


def test_two_queues_are_independent():
    a, b = CommandQueue(), CommandQueue()
    a.put(0x6083, 0, 1)
    assert b.pending_count() == 0
```

`tests/integration/test_sdo_over_vcan.py` の末尾に追記:

```python
def test_sdo_write_is_applied_within_one_step(running_sim, master):
    """CAN 経由の書き込みが、キュー経由でも実際にモデルへ届く。"""
    node = _remote(master, 1)
    node.sdo[0x6083].raw = 4321
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if running_sim.models[1].read_object(0x6083) == 4321:
            return
        time.sleep(0.01)
    assert running_sim.models[1].read_object(0x6083) == 4321
```

ファイル先頭の import に `import time` を追加してください。

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_command_queue.py -q 2>&1 | tail -10"`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.sim.command_queue'`

- [ ] **Step 3: `command_queue.py` を書く**

`omsim/sim/command_queue.py`:

```python
"""CAN 受信スレッドからシミュレーションループへ書込みを渡すキュー。

python-can の Notifier は専用スレッドでコールバックを呼ぶため、SDO の
書込みをその場で DriverModel に適用すると step() と競合する。実機の
ドライバは受信したコマンドを次の制御周期の先頭で適用するので、同じ形に
そろえる（仕様的にも正しく、競合も消える）。

読み出しはキューを通さない。副作用が無く、1ms 待たせると SDO の
タイムアウトを招くため。
"""
import collections
import threading

QueuedWrite = collections.namedtuple("QueuedWrite", ["index", "sub", "value"])


class CommandQueue(object):
    def __init__(self):
        self._lock = threading.Lock()
        self._items = collections.deque()

    def put(self, index, sub, value):
        with self._lock:
            self._items.append(QueuedWrite(index, sub, value))

    def pending_count(self):
        with self._lock:
            return len(self._items)

    def drain(self, model):
        """溜まった書込みを順に適用し、発生した例外の一覧を返す。

        1 件が失敗しても後続を捨てない。捨てると「マスタは書けたつもり
        なのにシミュレータが受け取っていない」という追跡困難な状態になる。
        """
        with self._lock:
            items = list(self._items)
            self._items.clear()

        errors = []
        for item in items:
            try:
                model.write_object(item.index, item.sub, item.value)
            except Exception as err:
                errors.append((item, err))
        return errors
```

- [ ] **Step 4: `od_bridge.py` を変更する**

`build_local_node` に `queue` 引数を足し、`queue` があれば write をキューに積む:

```python
def build_local_node(node_id, od, model, queue=None):
    node = canopen.LocalNode(node_id, od)

    def on_read(index, subindex, od):
        try:
            return model.read_object(index, subindex)
        except ObjectAccessError as err:
            raise canopen.SdoAbortedError(err.abort_code)

    def on_write(index, subindex, od, data):
        value = od.decode_raw(data)
        if queue is not None:
            # 受信スレッドから直接 model を触らない。適用は step() の先頭。
            queue.put(index, subindex, value)
            return
        try:
            model.write_object(index, subindex, value)
        except ObjectAccessError as err:
            raise canopen.SdoAbortedError(err.abort_code)

    node.add_read_callback(on_read)
    node.add_write_callback(on_write)
    node.driver_model = model
    return node
```

**注意**: キュー経由にすると、書込みの失敗（範囲外の値など）は SDO の abort としてマスタに返せなくなります。これは実機でも「受け付けはするが次周期で弾かれる」挙動があるため許容しますが、**キューの `drain` が返したエラーは必ずログに出してください**（Task 4 Step 5）。捨てると「黙って失敗する」になります。

- [ ] **Step 5: `manager.py` を変更する**

`omsim/sim/manager.py`:

1. import を追加:

```python
import logging

from omsim.sim.command_queue import CommandQueue

logger = logging.getLogger(__name__)
```

2. `__init__` でノードごとにキューを作り、`build_local_node` に渡す:

```python
        self.queues = {}
        for spec in specs:
            od = load_eds(spec.eds)
            model = DriverModel(node_id=spec.node_id)
            queue = CommandQueue()
            self.models[spec.node_id] = model
            self.queues[spec.node_id] = queue
            self.nodes[spec.node_id] = build_local_node(
                spec.node_id, od, model, queue=queue)
```

3. `step()` の**先頭**で drain する:

```python
    def step(self):
        dt = self.clock.advance()
        for node_id, model in self.models.items():
            for item, err in self.queues[node_id].drain(model):
                logger.warning(
                    "node%d: %04Xh:%02X への書込み %s が拒否されました: %s",
                    node_id, item.index, item.sub, item.value, err,
                )
            model.step(dt)
            self._drain_emcy(node_id, model)
```

- [ ] **Step 6: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_command_queue.py -v"`
Expected: 7 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -5"`
Expected: 全 passed

**既存テストが落ちる可能性があります**: `tests/integration/` で「SDO を書いた直後にモデルの値を読む」テストは、キューが drain されるまで反映されません。落ちたら「1 step 待つ」形に修正してください（実機と同じ挙動なので、テストの期待を変えるのが正しい）。修正内容を報告書に書くこと。

- [ ] **Step 7: コミット**

```bash
git add omsim/sim/command_queue.py omsim/node/od_bridge.py omsim/sim/manager.py tests/unit/test_command_queue.py tests/integration/test_sdo_over_vcan.py
git commit -m "fix: CAN 受信スレッドからの書込みをキュー化し step 先頭で適用する"
```

---

## Task 5: SnapshotHub（Web へ配る状態と CAN ログの保持）

**Files:**
- Create: `omsim/web/__init__.py`
- Create: `omsim/web/hub.py`
- Modify: `requirements.txt`
- Test: `tests/unit/test_web_hub.py`（新規）

**Interfaces:**
- Consumes: `NodeManager.snapshot()`、`Recorder.recent_frames(limit)`
- Produces:
  - `SnapshotHub(manager, recorder, history_size=600)`
  - `.capture() -> Dict[str, Any]` — 現在のスナップショットを取り、履歴に積み、それを返す
  - `.latest() -> Optional[Dict[str, Any]]`
  - `.history(limit=None) -> List[Dict[str, Any]]`
  - `.frames(limit=100) -> List[Dict[str, Any]]`
  - `.payload(frame_limit=50) -> Dict[str, Any]` — WebSocket で送る 1 メッセージ。キー: `sim_time`(float) / `nodes`(dict) / `frames`(list)

`SnapshotHub` は `omsim/web/` に置きますが、**FastAPI に依存しません**（純粋なデータ保持）。Web が無くても単体テストできます。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_web_hub.py`:

```python
from omsim.node.eds import DEFAULT_EDS_PATH
from omsim.sim.manager import NodeManager, NodeSpec
from omsim.sim.recorder import Recorder
from omsim.web.hub import SnapshotHub


def make_hub(history_size=600):
    specs = [
        NodeSpec(node_id=1, eds=DEFAULT_EDS_PATH),
        NodeSpec(node_id=2, eds=DEFAULT_EDS_PATH),
    ]
    manager = NodeManager(specs, network=None, realtime=False)
    recorder = Recorder(None)
    return SnapshotHub(manager, recorder, history_size=history_size), manager, recorder


def test_latest_is_none_before_first_capture():
    hub, _manager, recorder = make_hub()
    assert hub.latest() is None
    recorder.close()


def test_capture_returns_and_stores_the_snapshot():
    hub, manager, recorder = make_hub()
    manager.step()
    snap = hub.capture()
    assert snap["nodes"][1]["node_id"] == 1
    assert hub.latest() is snap
    assert len(hub.history()) == 1
    recorder.close()


def test_history_is_bounded():
    hub, manager, recorder = make_hub(history_size=10)
    for _ in range(50):
        manager.step()
        hub.capture()
    assert len(hub.history()) == 10
    recorder.close()


def test_history_limit_returns_the_newest():
    hub, manager, recorder = make_hub()
    for _ in range(5):
        manager.step()
        hub.capture()
    recent = hub.history(limit=2)
    assert len(recent) == 2
    assert recent[-1] is hub.latest()
    recorder.close()


def test_frames_come_from_the_recorder():
    hub, manager, recorder = make_hub()
    recorder.frame("bus", 0x701, bytes([0x00]), 0.0)
    assert len(hub.frames()) == 1
    assert hub.frames()[0]["can_id"] == 0x701
    recorder.close()


def test_payload_contains_every_node_and_the_frames():
    hub, manager, recorder = make_hub()
    manager.step()
    recorder.frame("bus", 0x701, bytes([0x00]), 0.0)
    hub.capture()
    payload = hub.payload()
    assert sorted(payload["nodes"]) == [1, 2]
    assert len(payload["frames"]) == 1
    assert "sim_time" in payload
    recorder.close()


def test_payload_before_capture_is_still_valid():
    hub, _manager, recorder = make_hub()
    payload = hub.payload()
    assert payload["nodes"] == {}
    assert payload["frames"] == []
    recorder.close()
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_web_hub.py -q 2>&1 | tail -10"`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.web'`

- [ ] **Step 3: 実装する**

`omsim/web/__init__.py`: 空ファイル

`omsim/web/hub.py`:

```python
"""Web へ配る状態スナップショットと CAN フレームを保持する。

FastAPI には依存しない。Web が無くても単体テストできるようにするため。
"""
import collections


class SnapshotHub(object):
    def __init__(self, manager, recorder, history_size=600):
        self._manager = manager
        self._recorder = recorder
        self._history = collections.deque(maxlen=history_size)

    def capture(self):
        snapshot = self._manager.snapshot()
        self._history.append(snapshot)
        return snapshot

    def latest(self):
        if not self._history:
            return None
        return self._history[-1]

    def history(self, limit=None):
        items = list(self._history)
        if limit is None:
            return items
        return items[-limit:]

    def frames(self, limit=100):
        return self._recorder.recent_frames(limit=limit)

    def payload(self, frame_limit=50):
        snapshot = self.latest()
        return {
            "sim_time": snapshot["sim_time"] if snapshot else 0.0,
            "nodes": snapshot["nodes"] if snapshot else {},
            "frames": self.frames(limit=frame_limit),
        }
```

`requirements.txt` に追記（既存行は変えない）:

```
fastapi==0.124.4
uvicorn==0.33.0
```

- [ ] **Step 4: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_web_hub.py -v"`
Expected: 7 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -2"`
Expected: 全 passed

- [ ] **Step 5: コミット**

```bash
git add omsim/web/__init__.py omsim/web/hub.py requirements.txt tests/unit/test_web_hub.py
git commit -m "feat: Web へ配る状態と CAN ログを保持する SnapshotHub"
```

---

## Task 6: FastAPI アプリ（REST + WebSocket + 静的配信）

**Files:**
- Create: `omsim/web/app.py`
- Create: `omsim/web/static/index.html`（この時点では最小限のプレースホルダ）
- Test: `tests/unit/test_web_app.py`（新規）

**Interfaces:**
- Consumes: `SnapshotHub`
- Produces:
  - `create_app(hub) -> fastapi.FastAPI`
  - `GET /api/state` → `hub.payload()` の JSON
  - `GET /api/stubs` → `{"stubs": [{"index": int, "sub": int, "reason": str}, ...]}`
  - `GET /` → `omsim/web/static/index.html`
  - `WS /ws` → 接続直後に 1 回、以降 100ms 間隔で `hub.payload()` を JSON で送る
  - `run_web(hub, host, port)` — uvicorn をバックグラウンドスレッドで起動し、`(server, thread)` を返す

テストは FastAPI の `TestClient` を使います（`fastapi.testclient.TestClient`、内部で `httpx` か `requests` を使うため、無ければ pip で入れる必要があります。**まず VM で使えるか実測確認してください**）。

- [ ] **Step 1: TestClient が使えるか実測確認する**

Run:
```bash
ssh -F .vm-ssh-config default "python3 -c \"
from fastapi.testclient import TestClient
print('TestClient ok')
\" 2>&1 | tail -3"
```

使えなければ `python3 -m pip install --user httpx` を試し、それでも駄目なら **`requirements.txt` に必要なものを追記して入れてから進めてください。** 入れたものは報告書に記録すること。

- [ ] **Step 2: 失敗するテストを書く**

`tests/unit/test_web_app.py`:

```python
import json

from fastapi.testclient import TestClient

from omsim.node.eds import DEFAULT_EDS_PATH
from omsim.sim.manager import NodeManager, NodeSpec
from omsim.sim.recorder import Recorder
from omsim.web.app import create_app
from omsim.web.hub import SnapshotHub


def make_client():
    specs = [
        NodeSpec(node_id=1, eds=DEFAULT_EDS_PATH),
        NodeSpec(node_id=2, eds=DEFAULT_EDS_PATH),
    ]
    manager = NodeManager(specs, network=None, realtime=False)
    recorder = Recorder(None)
    hub = SnapshotHub(manager, recorder)
    manager.step()
    hub.capture()
    return TestClient(create_app(hub)), manager, recorder


def test_state_endpoint_returns_every_node():
    client, _manager, recorder = make_client()
    body = client.get("/api/state").json()
    assert sorted(body["nodes"]) == ["1", "2"]
    assert "sim_time" in body
    recorder.close()


def test_state_endpoint_includes_frames():
    client, _manager, recorder = make_client()
    body = client.get("/api/state").json()
    assert isinstance(body["frames"], list)
    recorder.close()


def test_stubs_endpoint_lists_unimplemented_objects():
    client, _manager, recorder = make_client()
    body = client.get("/api/stubs").json()
    assert len(body["stubs"]) > 0
    entry = body["stubs"][0]
    assert set(entry) == {"index", "sub", "reason"}
    recorder.close()


def test_root_serves_the_page():
    client, _manager, recorder = make_client()
    response = client.get("/")
    assert response.status_code == 200
    assert "omsim" in response.text.lower()
    recorder.close()


def test_websocket_sends_a_payload_on_connect():
    client, _manager, recorder = make_client()
    with client.websocket_connect("/ws") as socket:
        payload = json.loads(socket.receive_text())
    assert sorted(payload["nodes"]) == ["1", "2"]
    recorder.close()
```

**注意**: JSON のキーは文字列になるため、ノード ID は `"1"` / `"2"` になります。

- [ ] **Step 3: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_web_app.py -q 2>&1 | tail -10"`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsim.web.app'`

- [ ] **Step 4: 実装する**

`omsim/web/app.py`:

```python
"""シミュレータの状態をブラウザへ配る FastAPI アプリ。

Web が落ちてもシミュレーション本体は動き続ける。ここは snapshot の
購読者に徹し、シミュレーション状態を書き換えない。
"""
import asyncio
import json
import os
import threading

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PUSH_INTERVAL_SECONDS = 0.1


def create_app(hub):
    app = FastAPI(title="omsim")

    @app.get("/api/state")
    def get_state():
        return hub.payload()

    @app.get("/api/stubs")
    def get_stubs():
        from omsim.driver.model import DriverModel

        return {
            "stubs": [
                {"index": index, "sub": sub, "reason": reason}
                for index, sub, reason in DriverModel.router.stubs()
            ]
        }

    @app.get("/")
    def get_index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.websocket("/ws")
    async def websocket_state(socket: WebSocket):
        # 型注釈は必須。FastAPI はこれを見て WebSocket 引数だと判断する。
        await socket.accept()
        try:
            while True:
                await socket.send_text(json.dumps(hub.payload(), default=str))
                await asyncio.sleep(PUSH_INTERVAL_SECONDS)
        except WebSocketDisconnect:
            return

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def run_web(hub, host="0.0.0.0", port=8080):
    """uvicorn をバックグラウンドスレッドで起動し (server, thread) を返す。"""
    import uvicorn

    config = uvicorn.Config(
        create_app(hub), host=host, port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server, thread
```

`omsim/web/static/index.html`（この時点では最小限。Task 8-10 で作り込む）:

```html
<!doctype html>
<html lang="ja">
  <head>
    <meta charset="utf-8" />
    <title>omsim モニタ</title>
  </head>
  <body>
    <h1>omsim モニタ</h1>
    <p>読み込み中…</p>
  </body>
</html>
```

- [ ] **Step 5: テストを通す**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_web_app.py -v"`
Expected: 5 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -2"`
Expected: 全 passed

- [ ] **Step 6: コミット**

```bash
git add omsim/web/app.py omsim/web/static/index.html tests/unit/test_web_app.py
git commit -m "feat: 状態を配る FastAPI アプリ (REST + WebSocket)"
```

---

## Task 7: omsim 本体に `--web-port` を統合する

**Files:**
- Modify: `omsim/apps/omsim_main.py`
- Test: `tests/unit/test_omsim_cli.py`（追記）

**Interfaces:**
- Consumes: `SnapshotHub`、`run_web`
- Produces: `omsim --web-port 8080` で Web サーバが同時に立ち上がる。既定は無効（`--web-port` 未指定なら Web を起動しない）

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_omsim_cli.py` の末尾に追記:

```python
def test_web_port_defaults_to_disabled():
    assert parse_args([]).web_port is None


def test_web_port_is_parsed():
    assert parse_args(["--web-port", "8080"]).web_port == 8080


def test_web_host_defaults_to_all_interfaces():
    assert parse_args([]).web_host == "0.0.0.0"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_omsim_cli.py -q 2>&1 | tail -10"`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'web_port'`

- [ ] **Step 3: 実装する**

`omsim/apps/omsim_main.py` の `parse_args` に追加:

```python
    parser.add_argument(
        "--web-port",
        type=int,
        default=None,
        help="指定するとブラウザ用の Web サーバをこのポートで起動する",
    )
    parser.add_argument("--web-host", default="0.0.0.0")
```

`main()` の、`manager.start()` の後に追加:

```python
    hub = None
    if args.web_port is not None:
        from omsim.web.app import run_web
        from omsim.web.hub import SnapshotHub

        hub = SnapshotHub(manager, recorder)
        run_web(hub, host=args.web_host, port=args.web_port)
        print("omsim web: http://{}:{}/".format(args.web_host, args.web_port))
```

主ループの中、`recorder.state(...)` を呼んでいる箇所の隣に追加:

```python
            if hub is not None and manager.clock.tick_count % 20 == 0:
                hub.capture()
```

（20 ステップ = 20ms ごとにスナップショットを取る。WebSocket の配信は 100ms 間隔なので十分。）

- [ ] **Step 4: テストを通し、実機で起動を確認する**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_omsim_cli.py -v"`
Expected: 全 passed

`vcan0` が無ければ復旧してから、実際に Web つきで起動して HTTP 応答を確認する:

```bash
rtk proxy ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && (nohup python3 -m omsim.apps.omsim_main --node 1 --node 2 --web-port 8080 --duration 8 > /tmp/web.log 2>&1 &) ; sleep 3; curl -s http://127.0.0.1:8080/api/state | head -c 400; echo; echo '--- stubs ---'; curl -s http://127.0.0.1:8080/api/stubs | head -c 300; echo; sleep 6; cat /tmp/web.log"
```

Expected: `/api/state` が `sim_time` と `nodes` を含む JSON を返し、`/api/stubs` がスタブ一覧を返す。実測出力を報告書に貼ること。

- [ ] **Step 5: コミット**

```bash
git add omsim/apps/omsim_main.py tests/unit/test_omsim_cli.py
git commit -m "feat: omsim に --web-port を追加し Web サーバを同時起動する"
```

---

## Task 8: ステータスモニタ（画面 1/3）

**Files:**
- Modify: `omsim/web/static/index.html`
- Create: `omsim/web/static/style.css`
- Create: `omsim/web/static/app.js`
- Test: `tests/unit/test_web_static.py`（新規）

**Interfaces:**
- Consumes: WebSocket `/ws` が送る `{sim_time, nodes, frames}`
- Produces: ノードごとのカードに、NMT 状態 / CiA402 状態 / Statusword のビット別ランプ / モード / 目標・指令・実速度[r/min] / 位置[increment] / トルク[‰] / アラームを表示

MEXE02 のステータスモニタを参考にした構成にします（設計書 7 節）。**ビルド不要の素の JavaScript** で書きます（VM に Node が無いため。Vue + Vite への移行は将来必要になってから）。

Statusword のビット名（HP-5143E 6.1 p34、実装済みの `state_machine.py` と一致させること）:

| bit | 名前 |
|---|---|
| 0 | Ready to switch on |
| 1 | Switched on |
| 2 | Operation enabled |
| 3 | Fault |
| 4 | Voltage enabled |
| 5 | Quick stop |
| 6 | Switch on disabled |
| 7 | Warning |
| 9 | Remote |
| 10 | Target reached |
| 11 | Internal limit active |
| 12 | Operation mode specific (pv: 速度 0) |

- [ ] **Step 1: 失敗するテストを書く**

静的ファイルの中身は JavaScript なので pytest では動作を検証できません。**「必要な要素と関数が存在すること」だけを検証**し、実際の描画は Step 5 の手動確認で見ます。

`tests/unit/test_web_static.py`:

```python
import os

STATIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "omsim",
    "web",
    "static",
)


def _read(name):
    with open(os.path.join(STATIC_DIR, name), encoding="utf-8") as handle:
        return handle.read()


def test_index_loads_the_script_and_style():
    html = _read("index.html")
    assert "app.js" in html
    assert "style.css" in html


def test_index_has_the_three_panes():
    html = _read("index.html")
    for pane_id in ("pane-status", "pane-waveform", "pane-canlog"):
        assert 'id="{}"'.format(pane_id) in html


def test_app_js_connects_to_the_websocket():
    js = _read("app.js")
    assert "/ws" in js
    assert "WebSocket" in js


def test_app_js_knows_every_statusword_bit_name():
    js = _read("app.js")
    for name in (
        "Ready to switch on",
        "Switched on",
        "Operation enabled",
        "Fault",
        "Voltage enabled",
        "Quick stop",
        "Switch on disabled",
        "Warning",
        "Remote",
        "Target reached",
        "Internal limit active",
    ):
        assert name in js


def test_app_js_renders_the_monitor_values():
    js = _read("app.js")
    for key in (
        "actual_velocity_rpm",
        "command_velocity_rpm",
        "target_velocity_rpm",
        "actual_position",
        "torque_permille",
        "statusword",
        "state",
        "alarm",
    ):
        assert key in js
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_web_static.py -q 2>&1 | tail -10"`
Expected: FAIL（`style.css` / `app.js` が無い、3 ペインが無い）

- [ ] **Step 3: `index.html` を書く**

`omsim/web/static/index.html`（全面置き換え）:

```html
<!doctype html>
<html lang="ja">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>omsim モニタ</title>
    <link rel="stylesheet" href="/static/style.css" />
  </head>
  <body>
    <header>
      <h1>omsim モニタ</h1>
      <span id="conn" class="badge">未接続</span>
      <span id="simtime" class="badge">t = 0.000 s</span>
    </header>

    <section id="pane-status">
      <h2>ステータスモニタ</h2>
      <div id="nodes"></div>
    </section>

    <section id="pane-waveform">
      <h2>波形モニタ</h2>
      <div id="charts"></div>
    </section>

    <section id="pane-canlog">
      <h2>CAN フレームログ</h2>
      <div class="toolbar">
        <input id="filter" type="text" placeholder="フィルタ (例: SDO, 6041, node1)" />
        <button id="pause">停止</button>
      </div>
      <pre id="canlog"></pre>
    </section>

    <script src="/static/app.js"></script>
  </body>
</html>
```

- [ ] **Step 4: `style.css` と `app.js`（ステータス部分）を書く**

`omsim/web/static/style.css`:

```css
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Segoe UI", "Noto Sans JP", sans-serif;
  font-size: 14px;
  background: #14171c;
  color: #e6e9ef;
}
header {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px; background: #1c2027; border-bottom: 1px solid #2b313b;
}
h1 { font-size: 16px; margin: 0; }
h2 { font-size: 14px; margin: 0 0 8px; color: #9aa4b2; }
section { padding: 12px 16px; border-bottom: 1px solid #2b313b; }
.badge {
  padding: 2px 8px; border-radius: 10px; font-size: 12px;
  background: #2b313b; color: #9aa4b2;
}
.badge.ok { background: #14432a; color: #7ee2a8; }
.badge.ng { background: #4a1d1d; color: #ff9c9c; }
#nodes { display: flex; flex-wrap: wrap; gap: 12px; }
.node {
  flex: 1 1 340px; min-width: 320px;
  background: #1c2027; border: 1px solid #2b313b; border-radius: 6px; padding: 12px;
}
.node h3 { margin: 0 0 8px; font-size: 14px; }
.kv { display: grid; grid-template-columns: 1fr auto; gap: 2px 12px; }
.kv dt { color: #9aa4b2; }
.kv dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }
.bits { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 10px; }
.bit {
  font-size: 11px; padding: 2px 6px; border-radius: 3px;
  background: #23282f; color: #6b7480; border: 1px solid #2b313b;
}
.bit.on { background: #14432a; color: #7ee2a8; border-color: #1d6b41; }
.bit.fault.on { background: #4a1d1d; color: #ff9c9c; border-color: #7a2f2f; }
.alarm { margin-top: 8px; font-size: 12px; }
.alarm.active { color: #ff9c9c; }
canvas { width: 100%; height: 120px; background: #1c2027; border: 1px solid #2b313b; border-radius: 6px; }
.chart { margin-bottom: 10px; }
.chart-label { font-size: 12px; color: #9aa4b2; margin-bottom: 2px; }
.toolbar { display: flex; gap: 8px; margin-bottom: 8px; }
.toolbar input { flex: 1; background: #1c2027; border: 1px solid #2b313b; color: #e6e9ef; padding: 4px 8px; border-radius: 4px; }
.toolbar button { background: #2b313b; border: none; color: #e6e9ef; padding: 4px 12px; border-radius: 4px; cursor: pointer; }
#canlog {
  margin: 0; max-height: 260px; overflow-y: auto;
  background: #10131a; border: 1px solid #2b313b; border-radius: 6px;
  padding: 8px; font-size: 12px; line-height: 1.5; white-space: pre-wrap;
}
```

`omsim/web/static/app.js`:

```javascript
"use strict";

// HP-5143E 6.1 (p34) の Statusword ビット割り当て。
// omsim/driver/state_machine.py の実装と一致させること。
var STATUSWORD_BITS = [
  [0, "Ready to switch on"],
  [1, "Switched on"],
  [2, "Operation enabled"],
  [3, "Fault"],
  [4, "Voltage enabled"],
  [5, "Quick stop"],
  [6, "Switch on disabled"],
  [7, "Warning"],
  [9, "Remote"],
  [10, "Target reached"],
  [11, "Internal limit active"],
  [12, "Speed is 0 (pv)"]
];

var state = { paused: false, filter: "", nodes: {} };

function el(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function fixed(value, digits) {
  if (value === null || value === undefined) return "-";
  return Number(value).toFixed(digits);
}

function renderStatus(nodes) {
  var container = document.getElementById("nodes");
  container.innerHTML = "";
  Object.keys(nodes).sort().forEach(function (nodeId) {
    var snap = nodes[nodeId];
    var card = el("div", "node");
    card.appendChild(el("h3", null, "node " + nodeId + "  /  " + snap.state));

    var kv = el("dl", "kv");
    [
      ["モード (6061h)", snap.mode],
      ["Statusword (6041h)", "0x" + (snap.statusword >>> 0).toString(16).toUpperCase()],
      ["目標速度 (60FFh)", fixed(snap.target_velocity_rpm, 1) + " r/min"],
      ["指令速度 (606Bh)", fixed(snap.command_velocity_rpm, 1) + " r/min"],
      ["実速度 (606Ch)", fixed(snap.actual_velocity_rpm, 1) + " r/min"],
      ["位置 (6064h)", snap.actual_position + " inc"],
      ["トルク (6077h)", fixed(snap.torque_permille, 0) + " ‰"]
    ].forEach(function (pair) {
      kv.appendChild(el("dt", null, pair[0]));
      kv.appendChild(el("dd", null, String(pair[1])));
    });
    card.appendChild(kv);

    var bits = el("div", "bits");
    STATUSWORD_BITS.forEach(function (entry) {
      var on = ((snap.statusword >> entry[0]) & 1) === 1;
      var chip = el("span", "bit" + (entry[0] === 3 ? " fault" : "") + (on ? " on" : ""),
        entry[0] + " " + entry[1]);
      bits.appendChild(chip);
    });
    card.appendChild(bits);

    var alarmText = snap.alarm === null || snap.alarm === undefined
      ? "アラーム: なし"
      : "アラーム: 0x" + Number(snap.alarm).toString(16).toUpperCase();
    var alarm = el("div", "alarm" + (snap.alarm ? " active" : ""), alarmText);
    if (snap.alarm_history && snap.alarm_history.length) {
      alarm.textContent += "  (履歴: " + snap.alarm_history.map(function (code) {
        return "0x" + Number(code).toString(16).toUpperCase();
      }).join(", ") + ")";
    }
    card.appendChild(alarm);

    container.appendChild(card);
  });
}

function onMessage(payload) {
  document.getElementById("simtime").textContent =
    "t = " + fixed(payload.sim_time, 3) + " s";
  state.nodes = payload.nodes;
  renderStatus(payload.nodes);
}

function connect() {
  var badge = document.getElementById("conn");
  var socket = new WebSocket("ws://" + location.host + "/ws");
  socket.onopen = function () {
    badge.textContent = "接続中";
    badge.className = "badge ok";
  };
  socket.onclose = function () {
    badge.textContent = "切断";
    badge.className = "badge ng";
    setTimeout(connect, 1000);
  };
  socket.onmessage = function (event) {
    if (state.paused) return;
    onMessage(JSON.parse(event.data));
  };
}

connect();
```

- [ ] **Step 5: テストを通し、ブラウザで実際に見る**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_web_static.py -v"`
Expected: 5 passed

**実際にブラウザで確認する**（VM の IP は `192.168.33.10`）:

```bash
rtk proxy ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && (nohup python3 -m omsim.apps.omsim_main --node 1 --node 2 --web-port 8080 --duration 300 > /tmp/web.log 2>&1 &) ; sleep 3; curl -s http://127.0.0.1:8080/ | head -20"
```

Windows のブラウザで `http://192.168.33.10:8080/` を開き、**2 台のノードカードが表示され、Statusword のビットランプが出ることを目視で確認**してください。確認できたら、その旨と `curl` の実測出力を報告書に書いてください。

（ブラウザで確認できない環境なら、`curl http://127.0.0.1:8080/api/state` の出力で代替し、その旨を正直に報告書に書くこと。）

- [ ] **Step 6: コミット**

```bash
git add omsim/web/static/index.html omsim/web/static/style.css omsim/web/static/app.js tests/unit/test_web_static.py
git commit -m "feat: Web のステータスモニタ (Statusword ビット表示つき)"
```

---

## Task 9: 波形モニタ（画面 2/3）

**Files:**
- Modify: `omsim/web/static/app.js`
- Test: `tests/unit/test_web_static.py`（追記）

**Interfaces:**
- Consumes: WebSocket が送るスナップショット（100ms 間隔）
- Produces: ノードごとに 速度[r/min] / 位置[increment] / トルク[‰] の 3 本を Canvas でスクロール表示

外部ライブラリを使わず Canvas に直接描きます（依存を増やさないため）。**過去 300 点（= 30 秒ぶん）を保持**します。

- [ ] **Step 1: 失敗するテストを追記**

`tests/unit/test_web_static.py` の末尾に追記:

```python
def test_app_js_has_a_waveform_buffer_and_canvas_drawing():
    js = _read("app.js")
    assert "HISTORY_POINTS" in js
    assert "getContext" in js
    assert "drawChart" in js


def test_app_js_charts_velocity_position_and_torque():
    js = _read("app.js")
    assert "SERIES" in js
    for key in ("actual_velocity_rpm", "actual_position", "torque_permille"):
        assert key in js
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_web_static.py -q 2>&1 | tail -8"`
Expected: 2 件 FAIL

- [ ] **Step 3: 実装する**

`omsim/web/static/app.js` の `var state = ...` の下に追加:

```javascript
var HISTORY_POINTS = 300;  // 100ms 間隔 x 300 = 30 秒ぶん

var SERIES = [
  { key: "actual_velocity_rpm", label: "速度 [r/min]", color: "#7ee2a8" },
  { key: "actual_position", label: "位置 [inc]", color: "#8ab4ff" },
  { key: "torque_permille", label: "トルク [‰]", color: "#ffcf7e" }
];

var history = {};  // nodeId -> { key -> [値] }

function pushHistory(nodes) {
  Object.keys(nodes).forEach(function (nodeId) {
    if (!history[nodeId]) {
      history[nodeId] = {};
      SERIES.forEach(function (series) { history[nodeId][series.key] = []; });
    }
    SERIES.forEach(function (series) {
      var buffer = history[nodeId][series.key];
      buffer.push(Number(nodes[nodeId][series.key]) || 0);
      if (buffer.length > HISTORY_POINTS) buffer.shift();
    });
  });
}

function drawChart(canvas, values, color) {
  var ctx = canvas.getContext("2d");
  var width = canvas.width = canvas.clientWidth;
  var height = canvas.height = canvas.clientHeight;
  ctx.clearRect(0, 0, width, height);

  if (!values.length) return;

  var min = Math.min.apply(null, values);
  var max = Math.max.apply(null, values);
  if (min === max) { min -= 1; max += 1; }
  var span = max - min;

  // 0 の基準線
  if (min < 0 && max > 0) {
    var zeroY = height - ((0 - min) / span) * height;
    ctx.strokeStyle = "#2b313b";
    ctx.beginPath();
    ctx.moveTo(0, zeroY);
    ctx.lineTo(width, zeroY);
    ctx.stroke();
  }

  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  values.forEach(function (value, index) {
    var x = (index / (HISTORY_POINTS - 1)) * width;
    var y = height - ((value - min) / span) * height;
    if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = "#6b7480";
  ctx.font = "10px sans-serif";
  ctx.fillText(max.toFixed(1), 4, 10);
  ctx.fillText(min.toFixed(1), 4, height - 3);
}

function renderCharts(nodes) {
  var container = document.getElementById("charts");
  Object.keys(nodes).sort().forEach(function (nodeId) {
    SERIES.forEach(function (series) {
      var id = "chart-" + nodeId + "-" + series.key;
      var wrapper = document.getElementById(id);
      if (!wrapper) {
        wrapper = el("div", "chart");
        wrapper.id = id;
        wrapper.appendChild(el("div", "chart-label",
          "node " + nodeId + " / " + series.label));
        wrapper.appendChild(document.createElement("canvas"));
        container.appendChild(wrapper);
      }
      drawChart(wrapper.querySelector("canvas"),
        history[nodeId] ? history[nodeId][series.key] : [], series.color);
    });
  });
}
```

`onMessage` に 2 行追加:

```javascript
function onMessage(payload) {
  document.getElementById("simtime").textContent =
    "t = " + fixed(payload.sim_time, 3) + " s";
  state.nodes = payload.nodes;
  renderStatus(payload.nodes);
  pushHistory(payload.nodes);
  renderCharts(payload.nodes);
}
```

- [ ] **Step 4: テストを通し、ブラウザで波形が動くことを確認する**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_web_static.py -v"`
Expected: 7 passed

**実際にモーターを回して波形が動くことを確認**してください:

```bash
rtk proxy ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && (nohup python3 -m omsim.apps.omsim_main --node 1 --node 2 --web-port 8080 --duration 300 > /tmp/web.log 2>&1 &) ; sleep 3; python3 -m omsim.apps.scenario tests/scenarios/two_nodes_pv.yaml | tail -5"
```

シナリオ実行中にブラウザ（`http://192.168.33.10:8080/`）で速度波形が立ち上がることを目視確認し、報告書に書いてください。

- [ ] **Step 5: コミット**

```bash
git add omsim/web/static/app.js tests/unit/test_web_static.py
git commit -m "feat: Web の波形モニタ (速度・位置・トルク)"
```

---

## Task 10: CAN フレームログ（画面 3/3）

**Files:**
- Modify: `omsim/web/static/app.js`
- Test: `tests/unit/test_web_static.py`（追記）

**Interfaces:**
- Consumes: WebSocket が送る `frames`（`{t, dir, can_id, data, text}` の配列）
- Produces: デコード済みの 1 行表示、フィルタ入力、停止/再開ボタン

**既知の制限**: SocketCAN の `receive_own_messages` が既定 `False` のため、**omsim 自身が送信したフレーム（SDO レスポンス、boot-up、EMCY）はログに出ません。** 受信フレームのみです。これは進捗台帳に記録済みの制限で、解消は送信時に明示的に記録する形（別途）で行います。**この制限を画面に注記として出してください。**

- [ ] **Step 1: 失敗するテストを追記**

`tests/unit/test_web_static.py` の末尾に追記:

```python
def test_app_js_renders_the_can_log_with_filter_and_pause():
    js = _read("app.js")
    assert "renderCanLog" in js
    assert "filter" in js
    assert "pause" in js


def test_index_notes_the_receive_only_limitation():
    html = _read("index.html")
    assert "受信" in html
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_web_static.py -q 2>&1 | tail -8"`
Expected: 2 件 FAIL

- [ ] **Step 3: 実装する**

`omsim/web/static/index.html` の CAN ログ節に注記を足す（`<pre id="canlog">` の直前）:

```html
      <p class="note">
        SocketCAN の receive_own_messages が既定で無効のため、omsim 自身が送信した
        フレーム (SDO レスポンス / boot-up / EMCY) は表示されません。受信フレームのみです。
      </p>
```

`omsim/web/static/style.css` に追加:

```css
.note { margin: 0 0 8px; font-size: 12px; color: #9aa4b2; }
```

`omsim/web/static/app.js` に追加:

```javascript
function renderCanLog(frames) {
  var pre = document.getElementById("canlog");
  var filter = state.filter.toLowerCase();
  var lines = frames.filter(function (frame) {
    if (!filter) return true;
    var haystack = (frame.text + " " + frame.can_id.toString(16) + " " + frame.data).toLowerCase();
    return haystack.indexOf(filter) !== -1;
  }).map(function (frame) {
    return fixed(frame.t, 3) + "  " +
      ("00" + frame.can_id.toString(16).toUpperCase()).slice(-3) + "  " +
      frame.text;
  });
  pre.textContent = lines.join("\n");
  pre.scrollTop = pre.scrollHeight;
}

document.getElementById("filter").addEventListener("input", function (event) {
  state.filter = event.target.value;
  renderCanLog(state.frames || []);
});

document.getElementById("pause").addEventListener("click", function (event) {
  state.paused = !state.paused;
  event.target.textContent = state.paused ? "再開" : "停止";
});
```

`onMessage` に追加:

```javascript
  state.frames = payload.frames;
  renderCanLog(payload.frames);
```

- [ ] **Step 4: テストを通し、実際にフレームが流れることを確認する**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest tests/unit/test_web_static.py -v"`
Expected: 9 passed

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -2"`
Expected: 全 passed

シナリオを流しながらブラウザで CAN ログに `SDO wr node1 6040h:00 = ...` のような行が流れることを目視確認し、報告書に書いてください。

- [ ] **Step 5: コミット**

```bash
git add omsim/web/static/index.html omsim/web/static/style.css omsim/web/static/app.js tests/unit/test_web_static.py
git commit -m "feat: Web の CAN フレームログ (フィルタ・停止つき)"
```

---

## Task 11: P2 の総仕上げ（README とヘッドレス確認）

**Files:**
- Modify: `README.md`
- Modify: `scripts/vagrant_provision.sh`
- Test: 手動確認 + 全テスト

**Interfaces:**
- Consumes: これまでの全成果
- Produces: Web の使い方が README に載り、依存が provisioning に反映される

- [ ] **Step 1: `requirements.txt` の依存が VM に入ることを確認する**

`scripts/vagrant_provision.sh` は `python3 -m pip install --user -r requirements.txt` を実行するので、Task 5 で追記した fastapi / uvicorn は入ります。**Task 6 で追加の依存（httpx など）を入れた場合は、`requirements.txt` に追記されているか確認してください。**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && bash scripts/vagrant_provision.sh 2>&1 | tail -10"`
Expected: エラーなく完了（冪等性の確認）

- [ ] **Step 2: Web が無くてもシミュレーションが動くことを確認する**

設計書 4.1 の「Web が居なくてもシミュレーションは完全に動く（CI ではヘッドレス）」を実測で確かめます。

Run:
```bash
ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m omsim.apps.omsim_main --node 1 --node 2 --duration 1 && echo 'ヘッドレス OK 終了コード '$?"
```
Expected: Web を起動せずに正常終了

- [ ] **Step 3: README に Web の節を追加する**

`README.md` に次の節を追加してください（既存の節は消さない）:

- **Web モニタ**: `python3 -m omsim.apps.omsim_main --node 1 --node 2 --web-port 8080` で起動し、`http://192.168.33.10:8080/`（VM の IP）をブラウザで開く
- 3 ペインの説明（ステータスモニタ / 波形モニタ / CAN フレームログ）
- **既知の制限**: omsim 自身が送信したフレームは CAN ログに出ない（`receive_own_messages` が既定で無効なため）
- **網羅率の確認**: `python3 -m omsim.apps.omsim_main --coverage` で EDS に対する実装網羅率と未実装オブジェクト一覧が出る
- **未実装スタブの確認**: `python3 -m omsim.apps.omsim_main --list-stubs`

- [ ] **Step 4: 最終確認**

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m pytest -q 2>&1 | tail -2"`
Expected: 全 passed、SKIP 0

Run: `ssh -F .vm-ssh-config default "cd /home/vagrant/KEISUU/omsim && python3 -m omsim.apps.omsim_main --coverage | head -8"`
実測出力を報告書に記録。

- [ ] **Step 5: コミット**

```bash
git add README.md scripts/vagrant_provision.sh
git commit -m "docs: Web モニタと網羅率確認の使い方を README に追加"
```

---

## 完了条件

- [ ] `python3 -m pytest -q` が VM 上で全 passed（SKIP 0）
- [ ] 層の依存規則が全方向で自動検証され、違反を実際に検出できることを確認済み
- [ ] 未実装オブジェクトへの SDO アクセスが abort し、`--coverage` で未実装の一覧が出る
- [ ] pv が `OperationMode` へ分離され、`DriverModel` が組み立て役に戻っている
- [ ] CAN 受信スレッドからの書込みがキュー経由になり、`step()` の先頭で適用される
- [ ] `omsim --node 1 --node 2 --web-port 8080` でブラウザから 3 ペインが見える
- [ ] シナリオ実行中に波形が動き、CAN ログが流れることを目視確認済み
- [ ] Web 無しでもシミュレーションが動く（ヘッドレス）ことを確認済み

## 次のフェーズ

P3（PDO 4+4 / 動的マッピング / transmission type / event timer / inhibit / SYNC / Heartbeat consumer / node guarding / `1003h`）は別計画。P2 で入れたコマンドキューが、P3 で PDO 受信スレッドを足すときの土台になります。

P2 で意図的に後回しにしたもの:
- omsim 自身の送信フレームを CAN ログに出す（送信時に `recorder.frame("tx", ...)` を明示的に呼ぶ形）
- 波形モニタのトリガ条件と時間軸ズーム（設計書 7 節）
- I/O モニタとアラームモニタのペイン（設計書 7 節。CN4 I/O は P5、アラーム全コードは P6 のため）
- 3D ビュー（設計書 7 節、P7）
