import pytest

from omsim.driver.errors import ABORT_NOT_WRITABLE, ObjectAccessError
from omsim.driver.model import DriverModel


def test_reports_its_node_id():
    assert DriverModel(node_id=3).snapshot()["node_id"] == 3


def test_device_name_is_readable():
    assert DriverModel(node_id=1).read_object(0x1008) == "BLVD-KRD"


def test_device_name_is_not_writable():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x1008, 0, 1)
    assert exc.value.abort_code == ABORT_NOT_WRITABLE


def test_unhandled_object_reads_as_none():
    assert DriverModel(node_id=1).read_object(0x1018, 1) is None


def test_step_accumulates_sim_time():
    model = DriverModel(node_id=1)
    for _ in range(1000):
        model.step(0.001)
    assert abs(model.sim_time - 1.0) < 1e-9
    assert abs(model.snapshot()["sim_time"] - 1.0) < 1e-9


def test_two_models_do_not_share_state():
    a, b = DriverModel(node_id=1), DriverModel(node_id=2)
    a.step(0.001)
    assert a.sim_time != b.sim_time
    assert b.sim_time == 0.0
