"""シナリオ結果の実測値と report.html。"""
import io
import os
import xml.etree.ElementTree as ET

from omsim.apps.scenario import Scenario, StepResult, write_junit, write_report


def make_results():
    return [
        StepResult(index=0, kind="nmt", ok=True, detail="", seconds=0.012, actual=None),
        StepResult(index=1, kind="expect", ok=True, detail="node1 actual=100",
                   seconds=0.35, actual=100),
        StepResult(index=2, kind="expect", ok=False,
                   detail="node1 actual=3 expected=100", seconds=2.0, actual=3),
    ]


SCENARIO = Scenario(name="デモ", nodes=[1], steps=[])


def test_step_result_carries_duration_and_actual():
    result = make_results()[1]
    assert result.seconds == 0.35
    assert result.actual == 100


def test_step_result_defaults_keep_old_call_sites_working():
    result = StepResult(index=0, kind="wait", ok=True, detail="")
    assert result.seconds == 0.0
    assert result.actual is None


def test_junit_includes_the_duration(tmp_path):
    path = str(tmp_path / "junit.xml")
    write_junit(make_results(), SCENARIO, path)
    suite = ET.parse(path).getroot()
    assert suite.get("tests") == "3"
    assert suite.get("failures") == "1"
    cases = suite.findall("testcase")
    assert cases[1].get("time") == "0.35"


def test_report_html_is_self_contained(tmp_path):
    path = str(tmp_path / "report.html")
    write_report(make_results(), SCENARIO, path)
    with io.open(path, encoding="utf-8") as handle:
        html = handle.read()
    assert "<html" in html
    # 外部参照を持たない (オフラインで開ける)
    assert "http://" not in html
    assert "https://" not in html
    assert "デモ" in html
    assert "PASS" in html and "FAIL" in html
    assert "0.35" in html
    assert "node1 actual=3 expected=100" in html


def test_report_says_there_is_no_can_log_when_none_was_recorded(tmp_path):
    path = str(tmp_path / "report.html")
    write_report(make_results(), SCENARIO, path)
    with io.open(path, encoding="utf-8") as handle:
        html = handle.read()
    assert "CAN ログの記録はありません" in html


def test_report_embeds_frames_around_a_failure(tmp_path):
    record = str(tmp_path / "rec.jsonl")
    with io.open(record, "w", encoding="utf-8") as out:
        out.write('{"kind": "frame", "t": 1.0, "dir": "bus", "can_id": 1537, '
                  '"data": "2f60600003", "text": "SDO wr node1 6060h:00"}\n')
        out.write('{"kind": "state", "t": 1.0, "snapshot": {}}\n')
    path = str(tmp_path / "report.html")
    write_report(make_results(), SCENARIO, path, record_path=record)
    with io.open(path, encoding="utf-8") as handle:
        html = handle.read()
    assert "SDO wr node1 6060h:00" in html
    assert "CAN ログの記録はありません" not in html


def test_report_escapes_html_in_details(tmp_path):
    results = [StepResult(index=0, kind="expect", ok=False,
                          detail="<script>alert(1)</script>", seconds=0.1, actual=None)]
    path = str(tmp_path / "report.html")
    write_report(results, SCENARIO, path)
    with io.open(path, encoding="utf-8") as handle:
        html = handle.read()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
