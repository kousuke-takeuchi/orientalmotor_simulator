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
