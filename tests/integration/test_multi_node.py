"""設計書 8.1 の複数ノード独立性の検証。"""
import os
import time

import canopen
import pytest

from omsim.apps.scenario import SDO_RESPONSE_TIMEOUT, load_scenario, run_scenario
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


def _wait_for_sdo_values(remotes, expected_values, timeout=2.0, interval=0.1):
    """
    SDO値が期待値になるまでリトライ（CAN経由書込みのキュー反映待機用）。

    Args:
        remotes: {node_id: RemoteNode} のdict
        expected_values: {node_id: expected_value} のdict
        timeout: 最大待ち時間（秒）
        interval: リトライ間隔（秒）

    Raises:
        AssertionError: タイムアウト時に実際の値を含むメッセージで失敗
    """
    start = time.time()
    while time.time() - start < timeout:
        all_match = True
        for node_id, expected in expected_values.items():
            actual = remotes[node_id].sdo[0x6083].raw
            if actual != expected:
                all_match = False
                break
        if all_match:
            return
        time.sleep(interval)

    # タイムアウト時は実際の値を含むメッセージで失敗
    actual_values = {node_id: remotes[node_id].sdo[0x6083].raw
                     for node_id in expected_values}
    raise AssertionError(
        u"SDO値が期待値になりません (timeout=%.1fs): 期待値=%s, 実際=%s"
        % (timeout, expected_values, actual_values)
    )


def test_scenario_two_nodes_reach_different_speeds(running_sim, master):
    scenario = load_scenario(SCENARIO)
    results = run_scenario(scenario, master)
    assert [r for r in results if not r.ok] == []


def test_fault_on_one_node_does_not_stop_the_other(stepped_sim):
    one = stepped_sim.models[1]
    two = stepped_sim.models[2]
    _enable(one, 100)
    _enable(two, 100)
    stepped_sim.run_for(2.0)

    one.inject_alarm(0x30, 0x2310)
    stepped_sim.run_for(1.5)

    assert abs(one.read_object(0x606C)) <= 2
    assert abs(two.read_object(0x606C) - 100) <= 2
    assert two.read_object(0x6041) & 0x6F == 0x27
    # 障害を注入した側 (one) が実際に Fault 状態になっていることを直接検証する。
    assert one.read_object(0x6041) & 0x4F == 0x08


def test_removing_excitation_on_one_node_does_not_affect_the_other(stepped_sim):
    one = stepped_sim.models[1]
    two = stepped_sim.models[2]
    _enable(one, 100)
    _enable(two, 100)
    stepped_sim.run_for(2.0)

    one.state_machine.voltage_enabled = False  # HWTO 相当。実装は P5
    stepped_sim.run_for(1.5)

    assert abs(one.read_object(0x606C)) <= 2
    assert abs(two.read_object(0x606C) - 100) <= 2
    # 励磁を落とした側 (one) が実際に switch-on-disabled かつ
    # Voltage Enabled ビットが落ちていることを直接検証する。
    assert one.read_object(0x6041) & 0x4F == 0x40
    assert one.read_object(0x6041) & (1 << 4) == 0


def test_parameters_do_not_leak_between_nodes(stepped_sim):
    one = stepped_sim.models[1]
    two = stepped_sim.models[2]
    one.write_object(0x6091, 1, 100)
    one.write_object(0x6091, 2, 1)
    assert one.units.gear_ratio == 100.0
    assert two.units.gear_ratio == 1.0


def test_nmt_reset_of_one_node_leaves_the_other_operational(running_sim, master):
    import time

    one = running_sim.models[1]
    two = running_sim.models[2]
    _enable(two, 100)
    time.sleep(2.0)

    master.send_message(0x000, bytes([0x81, 1]))  # reset node 1
    time.sleep(0.5)

    assert running_sim.nodes[2].nmt.state != "INITIALISING"
    assert abs(two.read_object(0x606C) - 100) <= 2
    assert one is running_sim.models[1]


def test_sdo_requests_to_both_nodes_are_not_confused(running_sim, master):
    remotes = {}
    for node_id in (1, 2):
        node = canopen.RemoteNode(node_id, DEFAULT_EDS_PATH)
        master.add_node(node)
        node.sdo.RESPONSE_TIMEOUT = SDO_RESPONSE_TIMEOUT
        remotes[node_id] = node

    remotes[1].sdo[0x6083].raw = 1234
    remotes[2].sdo[0x6083].raw = 4321

    # CAN経由SDO書込みはコマンドキュー経由のため、次のstep()で反映される。
    # キュー反映を待つ。
    _wait_for_sdo_values(remotes, {1: 1234, 2: 4321})

    # その後、20回読んでも取り違えない（2台のSDOが混ざらないことの検証）。
    for _ in range(20):
        assert remotes[1].sdo[0x6083].raw == 1234
        assert remotes[2].sdo[0x6083].raw == 4321


def test_emcy_cob_ids_differ_per_node(running_sim):
    assert running_sim.nodes[1].emcy.cob_id == 0x081
    assert running_sim.nodes[2].emcy.cob_id == 0x082
