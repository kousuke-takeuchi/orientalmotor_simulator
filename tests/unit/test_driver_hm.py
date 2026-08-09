"""hm (Homing) モード。HP-5143E 7.5 実測。

CW bit4 HOS (Homing operation start) / SW bit10 TR・bit12 HA・bit13 HE
サポートする方式: 17/18 (リミットセンサ)、24/28 (HOME センサ)、35/37 (現在位置)
"""
import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import MODE_HM, DriverModel

CW_ENABLE = 0x000F
CW_HOS = 1 << 4
SW_TR = 1 << 10
SW_HA = 1 << 12
SW_HE = 1 << 13


def hm_model(method=37):
    model = DriverModel(node_id=1)
    model.step(0.001)
    model.write_object(0x6060, 0, MODE_HM)
    model.write_object(0x6098, 0, method)
    for controlword in (0x0006, 0x0007, CW_ENABLE):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    return model


def run(model, milliseconds):
    for _ in range(milliseconds):
        model.step(0.001)


def start_homing(model):
    model.write_object(0x6040, 0, CW_ENABLE)
    model.step(0.001)
    model.write_object(0x6040, 0, CW_ENABLE | CW_HOS)
    model.step(0.001)


def test_mode_display_reports_hm():
    assert hm_model().read_object(0x6061) == MODE_HM


def test_defaults_match_the_manual():
    model = DriverModel(node_id=1)
    assert model.read_object(0x6098) == 37
    assert model.read_object(0x6099, 1) == 60
    assert model.read_object(0x6099, 2) == 30
    assert model.read_object(0x609A) == 1000
    assert model.read_object(0x607C) == 0


def test_unsupported_homing_methods_are_rejected():
    model = hm_model()
    for method in (1, 2, 8, 12, -1):
        with pytest.raises(ObjectAccessError):
            model.write_object(0x6098, 0, method)


def test_out_of_range_homing_method_is_rejected():
    model = hm_model()
    with pytest.raises(ObjectAccessError):
        model.write_object(0x6098, 0, 38)


def test_method_37_homes_on_the_current_position():
    model = hm_model(37)
    model.plant.preset_position(12345)
    start_homing(model)
    run(model, 10)
    assert model.read_object(0x6064) == 0
    assert model.read_object(0x6041) & SW_HA
    assert model.read_object(0x6041) & SW_TR


def test_method_35_behaves_like_37():
    model = hm_model(35)
    model.plant.preset_position(-500)
    start_homing(model)
    run(model, 10)
    assert model.read_object(0x6064) == 0


def test_home_offset_becomes_the_home_position():
    model = hm_model(37)
    model.write_object(0x607C, 0, 1000)
    start_homing(model)
    run(model, 10)
    assert model.read_object(0x6064) == 1000


def test_homing_is_not_attained_before_it_starts():
    model = hm_model(37)
    assert model.read_object(0x6041) & SW_HA == 0


def test_method_17_runs_negative_until_the_limit_switch_then_backs_off():
    model = hm_model(17)
    model.write_object(0x6099, 1, 300)
    model.write_object(0x6099, 2, 300)
    start_homing(model)
    run(model, 200)
    assert model.read_object(0x606C) < -1          # 負方向へ探索している
    assert model.read_object(0x6041) & SW_HA == 0

    model.set_limit_inputs(rv_ls=True)             # RV-LS に当たった
    run(model, 300)
    assert model.read_object(0x606C) > 1           # 反転して抜けにいく
    model.set_limit_inputs(rv_ls=False)            # センサから抜けた
    run(model, 2000)
    assert model.read_object(0x6041) & SW_HA
    assert model.read_object(0x6064) == 0


def test_method_18_runs_positive():
    model = hm_model(18)
    model.write_object(0x6099, 1, 300)
    start_homing(model)
    run(model, 200)
    assert model.read_object(0x606C) > 1


def test_method_24_uses_the_home_switch():
    model = hm_model(24)
    model.write_object(0x6099, 1, 300)
    model.write_object(0x6099, 2, 300)
    start_homing(model)
    run(model, 200)
    assert model.read_object(0x606C) > 1
    model.set_limit_inputs(home=True)
    run(model, 300)
    model.set_limit_inputs(home=False)
    run(model, 2000)
    assert model.read_object(0x6041) & SW_HA


def test_homing_error_when_the_drive_is_not_enabled():
    model = hm_model(17)
    model.write_object(0x6040, 0, 0x0006)   # shutdown
    model.step(0.001)
    model.write_object(0x6040, 0, 0x0006 | CW_HOS)
    run(model, 10)
    assert model.read_object(0x6041) & SW_HA == 0


def test_software_limits_are_enabled_only_after_homing():
    model = hm_model(37)
    model.write_object(0x607D, 1, -1000)
    model.write_object(0x607D, 2, 1000)
    assert model.software_limits_active is False
    start_homing(model)
    run(model, 10)
    assert model.software_limits_active is True
