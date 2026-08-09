"""I/O 原点復帰運転。HP-5141J 7 章 / 4160h・4161h 実測。

4160h (HOME) 原点復帰方法: 0=2センサ / 1=3センサ(既定) / 2=1方向回転 / 3=押し当て
4161h (HOME) 原点復帰開始方向: 0=−側 / 1=＋側 (既定)
HOME 信号 (割付 No. 36) の立ち上がりで開始する。
"""
import pytest

from omsim.driver.errors import NotImplementedObjectError, ObjectAccessError
from omsim.driver.model import DriverModel

R_IO_BASE = 16
CW_ENABLE = 0x000F
HOME_SIGNAL = 36


def homing_model(method=0, direction=1):
    model = DriverModel(node_id=1)
    model.set_remote_input_function(0, HOME_SIGNAL)
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    model.step(0.001)
    for controlword in (0x0006, 0x0007, CW_ENABLE):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    model.write_object(0x4160, 0, method)
    model.set_io_homing_direction(direction)
    return model


def run(model, milliseconds):
    for _ in range(milliseconds):
        model.step(0.001)


def press_home(model):
    model.write_object(0x403E, 0, 1 << R_IO_BASE)
    model.step(0.001)


def test_defaults_match_the_manual():
    model = DriverModel(node_id=1)
    assert model.read_object(0x4160) == 1     # 3センサ
    assert model.io_homing_direction == 1     # ＋側 (4161h は EDS に無く MEXE02 専用)
    assert model.read_object(0x4163) == 30    # 起動速度


def test_homing_method_range_is_enforced():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError):
        model.write_object(0x4160, 0, 4)


def test_two_sensor_homing_runs_to_the_limit_and_backs_off():
    model = homing_model(method=0, direction=1)
    press_home(model)
    run(model, 300)
    assert model.read_object(0x606C) > 1          # ＋側へ探索
    model.set_limit_inputs(fw_ls=True)            # リミットに当たった
    run(model, 400)
    assert model.read_object(0x606C) < -1         # 反転して脱出
    model.set_limit_inputs(fw_ls=False)
    run(model, 3000)
    assert model.io_homing_completed is True
    assert model.read_object(0x6064) == 0


def test_start_direction_is_honoured():
    model = homing_model(method=0, direction=0)   # −側から
    press_home(model)
    run(model, 300)
    assert model.read_object(0x606C) < -1


def test_home_offset_becomes_the_origin():
    model = homing_model(method=0, direction=1)
    model.write_object(0x607C, 0, 500)
    press_home(model)
    run(model, 200)
    model.set_limit_inputs(fw_ls=True)
    run(model, 400)
    model.set_limit_inputs(fw_ls=False)
    run(model, 3000)
    assert model.read_object(0x6064) == 500


def test_software_limits_become_active_after_io_homing():
    model = homing_model(method=0, direction=1)
    model.write_object(0x607D, 1, -1000)
    model.write_object(0x607D, 2, 1000)
    assert model.software_limits_active is False
    press_home(model)
    run(model, 200)
    model.set_limit_inputs(fw_ls=True)
    run(model, 400)
    model.set_limit_inputs(fw_ls=False)
    run(model, 3000)
    assert model.software_limits_active is True


def test_unimplemented_methods_are_reported_when_started():
    """3センサ / 1方向回転 / 押し当ては未実装。黙って別の動きをしない。"""
    for method in (1, 2, 3):
        model = homing_model(method=method)
        with pytest.raises(NotImplementedObjectError):
            model.start_io_homing()


def test_home_signal_needs_excitation():
    model = DriverModel(node_id=1)
    model.set_remote_input_function(0, HOME_SIGNAL)
    model.step(0.001)
    model.write_object(0x4160, 0, 0)
    press_home(model)
    run(model, 300)
    assert abs(model.read_object(0x606C)) < 1
