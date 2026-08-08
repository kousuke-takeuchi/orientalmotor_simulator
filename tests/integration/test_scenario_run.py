import os

import canopen
import pytest

from omsim.apps.scenario import _sdo_variable, load_scenario, run_scenario, write_junit
from omsim.node.eds import DEFAULT_EDS_PATH, find_eds

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


# 以下は CAN 通信を介さず、canopen のオブジェクト辞書レベルだけで
# _sdo_variable のサブインデックス分岐と符号往復を検証する（シミュレータ不要）。


def test_sdo_variable_returns_the_variable_itself_for_a_simple_object():
    """6040h (Controlword) はサブインデックスを持たない単純変数（ODVariable）。"""
    od = canopen.import_od(find_eds(DEFAULT_EDS_PATH))
    remote = canopen.RemoteNode(1, od)
    variable = _sdo_variable(remote, 0x6040, 0)
    assert isinstance(variable, canopen.sdo.base.SdoVariable)
    assert hasattr(type(variable), "raw")


def test_sdo_variable_indexes_into_the_subindex_for_an_array_object():
    """6091h (Gear ratio) はサブインデックスを持つ ODArray。sub=1 の要素を返すこと。

    修正前は `len(remote.object_dictionary[index])` （サブインデックス数）を
    バイト長として使っていたため、こうしたオブジェクトへの書き込みが壊れていた。
    """
    od = canopen.import_od(find_eds(DEFAULT_EDS_PATH))
    remote = canopen.RemoteNode(1, od)
    assert isinstance(od[0x6091], canopen.objectdictionary.ODArray)
    variable = _sdo_variable(remote, 0x6091, 1)
    assert isinstance(variable, canopen.sdo.base.SdoVariable)
    assert hasattr(type(variable), "raw")
    # 配列オブジェクト自体（サブインデックス無指定）には .raw が無い
    # （修正前は `len(remote.object_dictionary[index])` が配列のサブインデックス数を
    # 返すため、これをバイト長と誤認していた）
    with pytest.raises(AttributeError):
        remote.sdo[0x6091].raw


def test_signed_integer32_round_trips_negative_value_via_object_dictionary():
    """607Ah (Target position) / 60FFh (Target velocity) は INTEGER32。

    EDS のデータ型定義レベルで負値が符号付きのまま往復することを確認する
    （CAN 通信は不要）。修正前は `int.from_bytes(..., signed=False)` 決め打ちで
    負値が巨大な正の整数として誤読される問題があった。
    """
    od = canopen.import_od(find_eds(DEFAULT_EDS_PATH))
    for index in (0x607A, 0x60FF):
        variable = od[index]
        raw = variable.encode_raw(-100)
        assert variable.decode_raw(raw) == -100
