import time

import canopen
import pytest

from omsim.apps.scenario import SDO_RESPONSE_TIMEOUT
from omsim.driver.errors import ABORT_DEVICE_STATE, ABORT_VALUE_RANGE
from omsim.node.eds import DEFAULT_EDS_PATH

pytestmark = pytest.mark.vcan


def _remote(master, node_id):
    node = canopen.RemoteNode(node_id, DEFAULT_EDS_PATH)
    master.add_node(node)
    node.sdo.RESPONSE_TIMEOUT = SDO_RESPONSE_TIMEOUT
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


def test_sdo_write_out_of_range_is_acked_as_abort_over_vcan(running_sim, master):
    """6083h に範囲外 (0) を書くと、CAN 経由でも SDO abort が返る。

    修正前は queue に積まれた時点で「成功」として ACK され、モデル側の
    ABORT_VALUE_RANGE 拒否は NodeManager.step() の warning ログに埋もれて
    マスタには一切伝わらなかった（P2 最終ブランチレビューの指摘）。
    """
    node = _remote(master, 1)
    with pytest.raises(canopen.SdoAbortedError) as exc:
        node.sdo[0x6083].raw = 0
    assert exc.value.code == ABORT_VALUE_RANGE
    # 拒否された書込みなので、既定値のまま変わっていないこと。
    assert running_sim.models[1].read_object(0x6083) == 1000


def test_sdo_write_unimplemented_mode_is_acked_as_abort_over_vcan(running_sim, master):
    """6060h に未実装の運転モード (6 = hm) を書くと、CAN 経由でも SDO abort が返る。

    未実装モードの検出は CAN 越しに黙って握りつぶされてはならない。
    (pp/tq は P4 で実装済みなので、まだ未実装の hm で確認する)
    """
    node = _remote(master, 1)
    with pytest.raises(canopen.SdoAbortedError) as exc:
        node.sdo[0x6060].raw = 6
    assert exc.value.code == ABORT_DEVICE_STATE
    assert running_sim.models[1].read_object(0x6060) == 3  # MODE_PV の既定値
