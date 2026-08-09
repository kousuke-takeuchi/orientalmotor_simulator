import canopen
import pytest

from omsim.driver.errors import ABORT_DEVICE_STATE, ABORT_VALUE_RANGE, ObjectAccessError
from omsim.driver.model import DriverModel
from omsim.node.eds import DEFAULT_EDS_PATH, load_eds
from omsim.node.od_bridge import build_local_node
from omsim.sim.command_queue import CommandQueue


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


def test_queued_write_rejected_for_out_of_range_becomes_sdo_abort(od):
    """本番の唯一の経路（queue 付き）でも、拒否された書込みは SDO abort になる。

    6083h (Profile acceleration) は 1 以上でなければ ABORT_VALUE_RANGE で
    拒否される。queue に積む前に検証されなければならず、積まれてもいけない。
    """
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    node = build_local_node(1, od, model, queue=queue)
    with pytest.raises(canopen.SdoAbortedError) as exc:
        node.set_data(0x6083, 0, od[0x6083].encode_raw(0))
    assert exc.value.code == ABORT_VALUE_RANGE
    assert queue.pending_count() == 0
    assert model.profile_acceleration_rpm_s == 1000.0


def test_queued_write_rejected_for_unimplemented_mode_becomes_sdo_abort(od):
    """6060h (Modes of operation) への未実装モード書込みも、queue 付き経路で拒否される。"""
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    node = build_local_node(1, od, model, queue=queue)
    with pytest.raises(canopen.SdoAbortedError) as exc:
        node.set_data(0x6060, 0, od[0x6060].encode_raw(1))
    assert exc.value.code == ABORT_DEVICE_STATE
    assert queue.pending_count() == 0


def test_queued_write_accepted_is_applied_only_after_drain(od):
    """検証を通った正常な書込みは、従来どおりキュー経由で（step() まで遅れて）適用される。"""
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    node = build_local_node(1, od, model, queue=queue)
    node.set_data(0x6083, 0, od[0x6083].encode_raw(500))
    assert queue.pending_count() == 1
    assert model.profile_acceleration_rpm_s == 1000.0  # まだ適用されていない

    errors = queue.drain(model)
    assert errors == []
    assert model.profile_acceleration_rpm_s == 500.0


def test_validate_object_rejects_alarm_reset_without_running_its_side_effects(od):
    """40C0h のような副作用を伴う writer は、検証段階では実行されない。

    アラームの原因が解消していない状態で 40C0h に 1 を書くと拒否される
    はずだが、この検証呼び出し自体が state_machine.set_fault(False) 等の
    副作用を実際の model に及ぼしてはいけない（コピー上で実行し捨てる）。
    """
    model = DriverModel(node_id=1)
    model.inject_alarm(alarm_code=1, emcy_code=0x1000)
    with pytest.raises(ObjectAccessError):
        model.validate_object(0x40C0, 0, 1)
    assert model.alarms.is_active  # 検証だけでは解除されない


def test_sdo_server_cob_ids_follow_node_id(od):
    node = build_local_node(5, od, DriverModel(node_id=5))
    assert node.sdo.rx_cobid == 0x605
    assert node.sdo.tx_cobid == 0x585
