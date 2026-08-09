"""CI ワークフローの妥当性。YAML が壊れていたら CI が回らないので検査する。"""
import os

import yaml

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOW = os.path.join(HERE, ".github", "workflows", "ci.yml")


def load():
    with open(WORKFLOW, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_workflow_exists_and_parses():
    assert os.path.exists(WORKFLOW)
    assert load()["jobs"]["test"]["runs-on"].startswith("ubuntu")


def test_python_version_matches_the_vm():
    steps = load()["jobs"]["test"]["steps"]
    setup = [s for s in steps if s.get("uses", "").startswith("actions/setup-python")]
    assert setup and setup[0]["with"]["python-version"] == "3.8"


def test_vcan_is_set_up_before_the_tests():
    steps = load()["jobs"]["test"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert any("vcan" in name for name in names)
    vcan_index = next(i for i, name in enumerate(names) if "vcan" in name)
    test_index = next(i for i, name in enumerate(names) if "テスト" in name)
    assert vcan_index < test_index


def test_skipped_tests_fail_the_build():
    """vcan が使えないまま skip 0 を装うのを防ぐ。"""
    steps = load()["jobs"]["test"]["steps"]
    run = "\n".join(s.get("run", "") for s in steps)
    assert "skipped" in run
    assert "exit 1" in run


def test_report_artifacts_are_uploaded():
    steps = load()["jobs"]["test"]["steps"]
    upload = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    assert upload
    assert "report.html" in upload[0]["with"]["path"]
    assert "junit.xml" in upload[0]["with"]["path"]
