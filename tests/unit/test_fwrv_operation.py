"""FW/RV 運転 (JOG・インチング・連続運転)。HP-5141J 6 章 実測。

信号は R-IN の機能割付で与える (既定では割り付いていない)。
(JOG) 運転速度 = NET-ID 337 (既定 100 r/min)、(JOG) 移動量 = NET-ID 336 (既定 1 step)。
"""
from omsim.driver.model import DriverModel

R_IO_BASE = 16
CW_ENABLE = 0x000F

FW_JOG, RV_JOG, FW_JOG_P, FW_SPD, RV_SPD = 48, 49, 52, 58, 59


def fwrv_model():
    model = DriverModel(node_id=1)
    # R-IN0=FW-JOG / 1=RV-JOG / 2=FW-JOG-P / 3=FW-SPD / 4=RV-SPD
    for slot, number in enumerate((FW_JOG, RV_JOG, FW_JOG_P, FW_SPD, RV_SPD)):
        model.set_remote_input_function(slot, number)
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    model.step(0.001)
    for controlword in (0x0006, 0x0007, CW_ENABLE):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    return model


def run(model, milliseconds):
    for _ in range(milliseconds):
        model.step(0.001)


def press(model, *bits):
    value = 0
    for bit in bits:
        value |= 1 << (R_IO_BASE + bit)
    model.write_object(0x403E, 0, value)
    model.step(0.001)


def test_jog_defaults_match_the_manual():
    model = DriverModel(node_id=1)
    assert model.jog_velocity_rpm == 100
    assert model.jog_distance == 1


def test_fw_jog_runs_while_the_signal_is_on():
    model = fwrv_model()
    press(model, 0)
    run(model, 500)
    assert abs(model.read_object(0x606C) - 100) < 5


def test_jog_stops_when_the_signal_is_released():
    model = fwrv_model()
    press(model, 0)
    run(model, 500)
    press(model)
    run(model, 500)
    assert abs(model.read_object(0x606C)) < 2


def test_rv_jog_runs_backwards():
    model = fwrv_model()
    press(model, 1)
    run(model, 500)
    assert model.read_object(0x606C) < -50


def test_jog_speed_follows_the_parameter():
    model = fwrv_model()
    model.jog_velocity_rpm = 250
    press(model, 0)
    run(model, 600)
    assert abs(model.read_object(0x606C) - 250) < 8


def test_inching_moves_the_distance_once_per_edge():
    model = fwrv_model()
    model.jog_distance = 3600      # 1 回転
    model.jog_velocity_rpm = 300
    press(model, 2)
    run(model, 3000)
    assert abs(model.read_object(0x6064) - 3600) <= 30
    # 押しっぱなしでは繰り返さない
    run(model, 3000)
    assert abs(model.read_object(0x6064) - 3600) <= 30


def test_inching_repeats_on_the_next_edge():
    model = fwrv_model()
    model.jog_distance = 3600
    model.jog_velocity_rpm = 300
    press(model, 2)
    run(model, 3000)
    press(model)
    press(model, 2)
    run(model, 3000)
    assert abs(model.read_object(0x6064) - 7200) <= 60


def test_continuous_velocity_signals_run_while_held():
    model = fwrv_model()
    model.jog_velocity_rpm = 200
    press(model, 3)               # FW-SPD
    run(model, 600)
    assert abs(model.read_object(0x606C) - 200) < 8
    press(model, 4)               # RV-SPD へ切り替え
    run(model, 900)
    assert model.read_object(0x606C) < -100


def test_both_directions_at_once_do_not_move():
    model = fwrv_model()
    press(model, 0, 1)
    run(model, 500)
    assert abs(model.read_object(0x606C)) < 2


def test_jog_needs_excitation():
    model = DriverModel(node_id=1)
    model.set_remote_input_function(0, FW_JOG)
    model.step(0.001)
    press(model, 0)
    run(model, 300)
    assert abs(model.read_object(0x606C)) < 1
