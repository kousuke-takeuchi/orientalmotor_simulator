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
