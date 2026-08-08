import pytest

from omsim.driver.errors import ABORT_VALUE_RANGE, ObjectAccessError
from omsim.driver.units import UnitConverter


def test_default_gear_ratio_is_one_to_one():
    assert UnitConverter().gear_ratio == 1.0


def test_gear_ratio_of_one_hundred_matches_pitakuru_reduction():
    conv = UnitConverter()
    conv.set_gear_ratio(100, 1)
    assert conv.gear_ratio == 100.0


def test_increments_per_shaft_revolution_includes_gear_and_encoder():
    conv = UnitConverter(encoder_increments=3600, motor_revolutions=1)
    conv.set_gear_ratio(100, 1)
    assert conv.increments_per_shaft_rev == 360000.0


def test_rpm_round_trips_through_internal_units():
    conv = UnitConverter(encoder_increments=3600, motor_revolutions=1)
    conv.set_gear_ratio(100, 1)
    internal = conv.rpm_to_internal(30.0)
    assert abs(conv.internal_to_rpm(internal) - 30.0) < 1e-9


def test_thirty_rpm_at_gear_100_is_180000_increments_per_second():
    conv = UnitConverter(encoder_increments=3600, motor_revolutions=1)
    conv.set_gear_ratio(100, 1)
    assert abs(conv.rpm_to_internal(30.0) - 180000.0) < 1e-6


def test_zero_shaft_revolutions_is_rejected():
    conv = UnitConverter()
    with pytest.raises(ObjectAccessError) as exc:
        conv.set_gear_ratio(100, 0)
    assert exc.value.abort_code == ABORT_VALUE_RANGE


def test_zero_encoder_increments_is_rejected():
    conv = UnitConverter()
    with pytest.raises(ObjectAccessError) as exc:
        conv.set_encoder_resolution(0, 1)
    assert exc.value.abort_code == ABORT_VALUE_RANGE


def test_rejected_write_leaves_previous_value_intact():
    conv = UnitConverter()
    conv.set_gear_ratio(100, 1)
    with pytest.raises(ObjectAccessError):
        conv.set_gear_ratio(100, 0)
    assert conv.gear_ratio == 100.0


def test_two_converters_are_independent():
    a, b = UnitConverter(), UnitConverter()
    a.set_gear_ratio(100, 1)
    assert b.gear_ratio == 1.0
