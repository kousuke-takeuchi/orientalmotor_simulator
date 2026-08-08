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
