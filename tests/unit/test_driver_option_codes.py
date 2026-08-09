"""605Ah-605Eh と 6085h の SDO 窓口と、quick stop の実挙動。"""
import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import MODE_PV, DriverModel


def enabled_model(target_rpm=100, decel=1000):
    model = DriverModel(node_id=1)
    model.step(0.001)
    model.write_object(0x6060, 0, MODE_PV)
    model.write_object(0x6084, 0, decel)
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    model.write_object(0x60FF, 0, target_rpm)
    for _ in range(500):
        model.step(0.001)
    assert abs(model.actual_velocity_rpm - target_rpm) < 5
    return model


def run(model, milliseconds):
    for _ in range(milliseconds):
        model.step(0.001)


def test_defaults_match_the_manual():
    model = DriverModel(node_id=1)
    assert model.read_object(0x605A) == 2
    assert model.read_object(0x605B) == 0
    assert model.read_object(0x605C) == 1
    assert model.read_object(0x605D) == 1
    assert model.read_object(0x605E) == 2


def test_quick_stop_deceleration_default_and_write():
    model = DriverModel(node_id=1)
    assert model.read_object(0x6085) == model.read_object(0x6084)
    model.write_object(0x6085, 0, 5000)
    assert model.read_object(0x6085) == 5000


def test_out_of_range_option_codes_are_rejected():
    model = DriverModel(node_id=1)
    for index, bad in ((0x605A, 3), (0x605B, 2), (0x605C, 2), (0x605D, 0), (0x605E, 3)):
        with pytest.raises(ObjectAccessError):
            model.write_object(index, 0, bad)


def test_quick_stop_uses_the_quick_stop_ramp_by_default():
    """既定 (605Ah=2) は 6085h の減速度で減速し switch-on-disabled へ抜ける。

    実速度はプラントの 1 次遅れ (τ=20ms) が乗るので、ランプそのものは
    指令速度 (606Bh) で確認する。
    """
    model = enabled_model(decel=1000)
    model.write_object(0x6085, 0, 10000)   # 通常減速の 10 倍で止める
    model.write_object(0x6040, 0, 0x0002)  # quick stop
    run(model, 20)                          # 100rpm / 10000rpm/s = 10ms
    assert abs(model.command_velocity_rpm) < 1
    run(model, 200)
    assert abs(model.actual_velocity_rpm) < 2
    assert model.state_machine.state == "switch-on-disabled"


def test_quick_stop_option_code_6_stays_in_quick_stop_active():
    model = enabled_model()
    model.write_object(0x605A, 0, 6)
    model.write_object(0x6085, 0, 10000)
    model.write_object(0x6040, 0, 0x0002)
    run(model, 500)
    assert abs(model.actual_velocity_rpm) < 2
    assert model.state_machine.state == "quick-stop-active"


def test_quick_stop_option_code_0_stops_immediately():
    model = enabled_model()
    model.write_object(0x605A, 0, 0)
    model.write_object(0x6040, 0, 0x0002)
    run(model, 2)
    assert abs(model.actual_velocity_rpm) < 1
    assert model.state_machine.state == "switch-on-disabled"


def test_quick_stop_option_code_minus_1_stops_immediately_but_stays():
    model = enabled_model()
    model.write_object(0x605A, 0, -1)
    model.write_object(0x6040, 0, 0x0002)
    run(model, 5)
    assert abs(model.actual_velocity_rpm) < 1
    assert model.state_machine.state == "quick-stop-active"


def test_quick_stop_option_code_1_uses_the_normal_deceleration():
    model = enabled_model(decel=1000)
    model.write_object(0x605A, 0, 1)
    model.write_object(0x6085, 0, 100000)  # quick stop ramp は使われないはず
    model.write_object(0x6040, 0, 0x0002)
    run(model, 20)
    # 1000 rpm/s なら 20ms で 20rpm しか落ちない (指令速度で見る)
    assert model.command_velocity_rpm > 75
    run(model, 300)
    assert abs(model.actual_velocity_rpm) < 2


def test_quick_stop_option_code_is_no_longer_a_stub():
    model = DriverModel(node_id=1)
    keys = set((index, sub) for index, sub, _reason in model.stub_objects())
    assert (0x605A, 0) not in keys
