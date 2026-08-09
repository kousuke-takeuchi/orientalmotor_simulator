"""運転方式テーブル。HP-5141J 3-4「運転方式一覧」実測。"""
import pytest

from omsim.driver.errors import NotImplementedObjectError, ObjectAccessError
from omsim.driver.operation_type import (
    OPERATION_TYPES,
    TYPE_ABSOLUTE,
    TYPE_CONTINUOUS_VELOCITY,
    TYPE_DECELERATION_STOP,
    TYPE_IMMEDIATE_STOP,
    TYPE_RELATIVE_COMMAND,
    TYPE_RELATIVE_DETECTED,
    resolve_operation_type,
)


def test_supported_types_resolve_to_their_names():
    assert resolve_operation_type(TYPE_DECELERATION_STOP) == "deceleration_stop"
    assert resolve_operation_type(TYPE_ABSOLUTE) == "absolute"
    assert resolve_operation_type(TYPE_RELATIVE_COMMAND) == "relative_command"
    assert resolve_operation_type(TYPE_RELATIVE_DETECTED) == "relative_detected"
    assert resolve_operation_type(TYPE_CONTINUOUS_VELOCITY) == "continuous_velocity"
    assert resolve_operation_type(TYPE_IMMEDIATE_STOP) == "immediate_stop"


def test_values_match_the_manual():
    assert TYPE_DECELERATION_STOP == 0
    assert TYPE_ABSOLUTE == 1
    assert TYPE_RELATIVE_COMMAND == 2
    assert TYPE_RELATIVE_DETECTED == 3
    assert TYPE_CONTINUOUS_VELOCITY == 16
    assert TYPE_IMMEDIATE_STOP == 32


@pytest.mark.parametrize("value", [4, 5, 6, 7, 8, 12, 17, 20, 23, 31, 39, 48, 51])
def test_known_but_unimplemented_types_are_reported_as_not_implemented(value):
    """表にはあるがこのフェーズで実装しない方式。黙って別の動きをしない。"""
    assert value in OPERATION_TYPES
    with pytest.raises(NotImplementedObjectError):
        resolve_operation_type(value)


@pytest.mark.parametrize("value", [-1, 24, 33, 52, 256])
def test_values_outside_the_table_are_rejected(value):
    with pytest.raises(ObjectAccessError):
        resolve_operation_type(value)
