"""tq (Profile Torque) モード。HP-5143E 7.4 実測。

6071h Target torque (-1000..1000, 0.1%) / 6072h Max torque (0..10000) /
6074h Torque demand / 6087h Torque slope (0..1,000,000, 0.1%/s)
Controlword bit8 HALT / Statusword bit10 TR・bit15 TLC
"""
import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import MODE_TQ, DriverModel

CW_ENABLE = 0x000F
CW_HALT = 1 << 8
SW_TR = 1 << 10
SW_TLC = 1 << 15


def tq_model(profile_velocity=300):
    model = DriverModel(node_id=1)
    model.step(0.001)
    model.write_object(0x6060, 0, MODE_TQ)
    model.write_object(0x6081, 0, profile_velocity)
    for controlword in (0x0006, 0x0007, CW_ENABLE):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    return model


def run(model, milliseconds):
    for _ in range(milliseconds):
        model.step(0.001)


def test_mode_display_reports_tq():
    assert tq_model().read_object(0x6061) == MODE_TQ


def test_target_torque_range_is_enforced():
    model = tq_model()
    model.write_object(0x6071, 0, 500)
    assert model.read_object(0x6071) == 500
    for bad in (-1001, 1001):
        with pytest.raises(ObjectAccessError):
            model.write_object(0x6071, 0, bad)


def test_torque_slope_range_is_enforced():
    model = tq_model()
    model.write_object(0x6087, 0, 1000)
    assert model.read_object(0x6087) == 1000
    with pytest.raises(ObjectAccessError):
        model.write_object(0x6087, 0, 1000001)


def test_torque_demand_follows_the_slope():
    model = tq_model()
    model.write_object(0x6087, 0, 100)   # 100 (0.1%)/s
    model.write_object(0x6071, 0, 50)
    run(model, 100)                       # 0.1 秒 -> 10
    assert 8 <= model.read_object(0x6074) <= 12
    run(model, 500)
    assert model.read_object(0x6074) == 50


def test_zero_slope_applies_the_target_immediately():
    model = tq_model()
    assert model.read_object(0x6087) == 0
    model.write_object(0x6071, 0, 30)
    run(model, 2)
    assert model.read_object(0x6074) == 30


def test_torque_accelerates_the_motor():
    model = tq_model()
    model.write_object(0x6071, 0, 20)
    run(model, 300)
    assert model.read_object(0x606C) > 5


def test_velocity_is_limited_by_profile_velocity():
    model = tq_model(profile_velocity=50)
    model.write_object(0x6071, 0, 200)
    run(model, 2000)
    assert abs(model.read_object(0x606C)) <= 51


def test_negative_torque_drives_backwards():
    model = tq_model()
    model.write_object(0x6071, 0, -20)
    run(model, 300)
    assert model.read_object(0x606C) < -5


def test_demand_is_clamped_by_max_torque_and_sets_tlc():
    model = tq_model()
    model.write_object(0x6072, 0, 40)
    model.write_object(0x6071, 0, 900)
    run(model, 10)
    assert model.read_object(0x6074) == 40
    assert model.read_object(0x6041) & SW_TLC


def test_target_reached_when_the_target_torque_is_reached():
    model = tq_model()
    model.write_object(0x6071, 0, 20)
    run(model, 10)
    assert model.read_object(0x6041) & SW_TR


def test_halt_ramps_the_torque_down_and_stops():
    model = tq_model()
    model.write_object(0x6071, 0, 100)
    run(model, 500)
    model.write_object(0x6040, 0, CW_ENABLE | CW_HALT)
    run(model, 1000)
    assert model.read_object(0x6074) == 0
    assert abs(model.read_object(0x606C)) < 2
    assert model.read_object(0x6041) & SW_TR   # HALT=1 のときは「停止した」


def test_max_torque_is_no_longer_a_stub():
    model = DriverModel(node_id=1)
    keys = set((index, sub) for index, sub, _reason in model.stub_objects())
    assert (0x6072, 0) not in keys
