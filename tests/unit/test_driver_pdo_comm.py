import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import DriverModel
from omsim.driver.pdo import PDO_RTR_BIT, PDO_VALID_BIT


def test_default_rpdo_cob_ids_follow_node_id():
    model = DriverModel(node_id=5)
    assert [c.cob_id for c in model.rpdo_comm] == [0x205, 0x305, 0x405, 0x505]
    assert all(c.valid for c in model.rpdo_comm)


def test_default_tpdo_cob_ids_follow_node_id_and_forbid_rtr():
    model = DriverModel(node_id=5)
    assert [c.cob_id for c in model.tpdo_comm] == [0x185, 0x285, 0x385, 0x485]
    assert all(c.valid and not c.rtr_allowed for c in model.tpdo_comm)


def test_default_transmission_types_match_eds():
    model = DriverModel(node_id=1)
    assert [c.transmission_type for c in model.rpdo_comm] == [255, 255, 255, 255]
    # 1800h/1801h は 255、1802h/1803h は 1 (EDS 実測値)
    assert [c.transmission_type for c in model.tpdo_comm] == [255, 255, 1, 1]


def test_default_inhibit_time_matches_eds():
    model = DriverModel(node_id=1)
    assert all(c.inhibit_time_100us == 50 for c in model.tpdo_comm)


def test_read_rpdo1_cob_id_sub1():
    model = DriverModel(node_id=3)
    assert model.read_object(0x1400, 1) == 0x203  # bit31/30 とも 0


def test_read_tpdo1_cob_id_sub1_has_rtr_bit_set():
    model = DriverModel(node_id=3)
    assert model.read_object(0x1800, 1) == (0x183 | PDO_RTR_BIT)


def test_write_transmission_type_updates_params():
    model = DriverModel(node_id=1)
    model.write_object(0x1800, 2, 5)
    assert model.tpdo_comm[0].transmission_type == 5


def test_write_reserved_tpdo_transmission_type_is_rejected():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x1800, 2, 0xF5)
    assert exc.value.abort_code == 0x06090030


def test_write_unsupported_rpdo_transmission_type_is_rejected():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x1400, 2, 0x01)  # RPDO は 0x00/0xFE/0xFF のみ
    assert exc.value.abort_code == 0x06090030


def test_write_inhibit_time():
    model = DriverModel(node_id=1)
    model.write_object(0x1800, 3, 100)
    assert model.tpdo_comm[0].inhibit_time_100us == 100


def test_write_event_timer():
    model = DriverModel(node_id=1)
    model.write_object(0x1800, 5, 200)
    assert model.tpdo_comm[0].event_timer_ms == 200


def test_disabling_then_enabling_a_pdo_round_trips():
    model = DriverModel(node_id=1)
    disabled = model.rpdo_comm[0].cob_id | PDO_VALID_BIT
    model.write_object(0x1400, 1, disabled)
    assert model.rpdo_comm[0].valid is False
    model.write_object(0x1400, 1, model.rpdo_comm[0].cob_id)  # 再度有効化
    assert model.rpdo_comm[0].valid is True


def test_all_four_rpdo_and_tpdo_slots_are_registered():
    model = DriverModel(node_id=1)
    for index in (0x1400, 0x1401, 0x1402, 0x1403):
        assert model.read_object(index, 0) == 2
    for index in (0x1800, 0x1801, 0x1802, 0x1803):
        assert model.read_object(index, 0) == 5
