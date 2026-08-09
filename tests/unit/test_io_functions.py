"""R-IN / R-OUT の機能割付。HP-5141J 14-1/14-2・13-10 実測。"""
import pytest

from omsim.driver.io_functions import (
    INPUT_FUNCTIONS,
    OUTPUT_FUNCTIONS,
    R_IN_DEFAULTS,
    input_function_name,
)
from omsim.driver.model import DriverModel

R_IO_BASE = 16


def test_assignment_numbers_match_the_manual():
    assert INPUT_FUNCTIONS[0] == "未使用"
    assert INPUT_FUNCTIONS[2] == "S-ON"
    assert INPUT_FUNCTIONS[32] == "START"
    assert INPUT_FUNCTIONS[36] == "HOME"
    assert INPUT_FUNCTIONS[48] == "FW-JOG"
    assert INPUT_FUNCTIONS[49] == "RV-JOG"
    assert INPUT_FUNCTIONS[80] == "D-SEL0"
    assert INPUT_FUNCTIONS[87] == "D-SEL7"
    assert OUTPUT_FUNCTIONS[2] == "S-ON_R"


def test_default_r_in_assignment_matches_the_manual():
    """R-IN0-7 = S-ON/PLOOP-MODE/TRQ-LMT/CLR/QSTOP/STOP/FREE/ALM-RST、R-IN8-15 = D-SEL0-7。"""
    assert [input_function_name(n) for n in R_IN_DEFAULTS[:8]] == [
        "S-ON", "PLOOP-MODE", "TRQ-LMT", "CLR", "QSTOP", "STOP", "FREE", "ALM-RST"]
    assert [input_function_name(n) for n in R_IN_DEFAULTS[8:]] == [
        "D-SEL{}".format(i) for i in range(8)]


def test_model_starts_with_the_default_assignment():
    model = DriverModel(node_id=1)
    assert model.remote_input_assignment == list(R_IN_DEFAULTS)


def test_remote_signal_reads_through_the_assignment():
    model = DriverModel(node_id=1)
    model.write_object(0x403E, 0, 1 << (R_IO_BASE + 5))    # R-IN5 = STOP (既定)
    assert model.remote_signal("STOP") is True
    assert model.remote_signal("FREE") is False


def test_reassigning_a_slot_changes_which_bit_means_what():
    model = DriverModel(node_id=1)
    model.set_remote_input_function(5, 32)                 # R-IN5 を START に
    model.write_object(0x403E, 0, 1 << (R_IO_BASE + 5))
    assert model.remote_signal("START") is True
    assert model.remote_signal("STOP") is False


def test_unknown_assignment_number_is_rejected():
    model = DriverModel(node_id=1)
    with pytest.raises(ValueError):
        model.set_remote_input_function(0, 999)


def test_unassigned_signal_is_simply_off():
    model = DriverModel(node_id=1)
    model.write_object(0x403E, 0, 0xFFFF0000)   # 全ビット ON
    # START は既定では割り付いていないので、いくら立てても ON にならない
    assert model.remote_signal("START") is False


def test_free_still_works_through_the_assignment():
    """P5 で固定ビット参照だった FREE も割付表経由で動くこと。"""
    model = DriverModel(node_id=1)
    model.step(0.001)
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    assert model.plant.excited is True
    model.write_object(0x403E, 0, 1 << (R_IO_BASE + 6))    # R-IN6 = FREE
    model.step(0.001)
    assert model.plant.excited is False


def test_free_moves_with_the_assignment():
    model = DriverModel(node_id=1)
    model.set_remote_input_function(0, 1)       # R-IN0 を FREE に
    model.set_remote_input_function(6, 2)       # R-IN6 を S-ON に
    model.step(0.001)
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    model.write_object(0x403E, 0, 1 << (R_IO_BASE + 0))    # 新しい FREE の位置
    model.step(0.001)
    assert model.plant.excited is False
