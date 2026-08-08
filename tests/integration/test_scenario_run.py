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
