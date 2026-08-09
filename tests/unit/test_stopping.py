"""停止動作と option code の解釈。HP-5143E 605Ah-605Eh 実測。"""
import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.stopping import (
    IMMEDIATE,
    QUICK_STOP_RAMP,
    SLOW_DOWN,
    CUSTOM_RATE,
    CUSTOM_TIME,
    resolve_disable_operation,
    resolve_fault_reaction,
    resolve_halt,
    resolve_quick_stop,
    resolve_shutdown,
)


# 605Ah: −3〜6 (既定 2)
@pytest.mark.parametrize("code,kind,stay", [
    (-3, CUSTOM_TIME, True),
    (-2, CUSTOM_RATE, True),
    (-1, IMMEDIATE, True),
    (0, IMMEDIATE, False),
    (1, SLOW_DOWN, False),
    (2, QUICK_STOP_RAMP, False),
    (5, SLOW_DOWN, True),
    (6, QUICK_STOP_RAMP, True),
])
def test_quick_stop_option_codes(code, kind, stay):
    action = resolve_quick_stop(code)
    assert action.kind == kind
    assert action.stay_in_state is stay


@pytest.mark.parametrize("code", [-4, 3, 4, 7])
def test_unsupported_quick_stop_option_codes_are_rejected(code):
    with pytest.raises(ObjectAccessError):
        resolve_quick_stop(code)


# 605Bh: 0〜1 (既定 0)
def test_shutdown_option_codes():
    assert resolve_shutdown(0).kind == IMMEDIATE
    assert resolve_shutdown(1).kind == SLOW_DOWN
    with pytest.raises(ObjectAccessError):
        resolve_shutdown(2)


# 605Ch: 0〜1 (既定 1)
def test_disable_operation_option_codes():
    assert resolve_disable_operation(0).kind == IMMEDIATE
    assert resolve_disable_operation(1).kind == SLOW_DOWN
    with pytest.raises(ObjectAccessError):
        resolve_disable_operation(-1)


# 605Dh: 0 は予約、1 のみ有効 (既定 1)
def test_halt_option_code_zero_is_reserved():
    assert resolve_halt(1).kind == SLOW_DOWN
    with pytest.raises(ObjectAccessError):
        resolve_halt(0)


# 605Eh: 0〜2 (既定 2)
def test_fault_reaction_option_codes():
    assert resolve_fault_reaction(0).kind == IMMEDIATE
    assert resolve_fault_reaction(0).non_excitation is True
    assert resolve_fault_reaction(1).kind == SLOW_DOWN
    assert resolve_fault_reaction(2).kind == QUICK_STOP_RAMP
    with pytest.raises(ObjectAccessError):
        resolve_fault_reaction(3)
