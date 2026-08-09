import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import DriverModel


def test_default_sync_cob_id_is_0x80():
    model = DriverModel(node_id=1)
    assert model.read_object(0x1005) == 0x80
    assert model.sync_producer_enabled is False


def test_writing_bit30_enables_producer_mode():
    model = DriverModel(node_id=1)
    model.write_object(0x1005, 0, 0x80 | (1 << 30))
    assert model.sync_producer_enabled is True
    assert model.sync_cob_id == 0x80


def test_writing_cob_id_updates_sync_cob_id():
    model = DriverModel(node_id=1)
    model.write_object(0x1005, 0, 0x90)
    assert model.sync_cob_id == 0x90


def test_default_communication_cycle_period_is_zero():
    model = DriverModel(node_id=1)
    assert model.read_object(0x1006) == 0
    assert model.sync_period_us == 0


def test_writing_communication_cycle_period():
    model = DriverModel(node_id=1)
    model.write_object(0x1006, 0, 10000)
    assert model.sync_period_us == 10000


def test_communication_cycle_period_out_of_range_is_rejected():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError):
        model.write_object(0x1006, 0, 1000001)
