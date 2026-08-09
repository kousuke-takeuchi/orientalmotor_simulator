"""ソフトウェアリミット (607Dh) とリミットセンサ。HP-5143E 607Dh / 60FDh 実測。"""
from omsim.driver.model import MODE_PP, MODE_PV, DriverModel

CW_ENABLE = 0x000F
CW_NSP = 1 << 4
SW_ILA = 1 << 11


def pv_model(target=200):
    model = DriverModel(node_id=1)
    model.step(0.001)
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    for controlword in (0x0006, 0x0007, CW_ENABLE):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    model.write_object(0x60FF, 0, target)
    return model


def run(model, milliseconds):
    for _ in range(milliseconds):
        model.step(0.001)


def home(model):
    """現在位置で原点復帰を済ませ、ソフトリミットを有効にできる状態にする。"""
    model.write_object(0x6060, 0, 6)
    model.write_object(0x6098, 0, 37)
    model.write_object(0x6040, 0, CW_ENABLE)
    model.step(0.001)
    model.write_object(0x6040, 0, CW_ENABLE | CW_NSP)
    run(model, 5)
    model.write_object(0x6060, 0, MODE_PV)


def test_software_limits_are_disabled_when_min_equals_max():
    model = pv_model()
    home(model)
    model.write_object(0x607D, 1, 500)
    model.write_object(0x607D, 2, 500)
    assert model.software_limits_active is False


def test_software_limits_are_disabled_when_min_is_greater_than_max():
    model = pv_model()
    home(model)
    model.write_object(0x607D, 1, 900)
    model.write_object(0x607D, 2, 100)
    assert model.software_limits_active is False


def test_positive_software_limit_stops_the_motor_and_sets_ila():
    model = pv_model(target=200)
    home(model)
    model.write_object(0x607D, 1, -3600)
    model.write_object(0x607D, 2, 3600)
    run(model, 3000)
    position = model.read_object(0x6064)
    assert position <= 3600 + 50
    assert abs(model.read_object(0x606C)) < 2
    assert model.read_object(0x6041) & SW_ILA


def test_negative_software_limit_stops_the_motor():
    model = pv_model(target=-200)
    home(model)
    model.write_object(0x607D, 1, -3600)
    model.write_object(0x607D, 2, 3600)
    run(model, 3000)
    assert model.read_object(0x6064) >= -3600 - 50
    assert model.read_object(0x6041) & SW_ILA


def test_home_offset_shifts_the_limits():
    """607Dh は home offset (607Ch) を引いた値と比較する (HP-5143E 実測)。"""
    model = pv_model(target=200)
    model.write_object(0x607C, 0, 1000)
    home(model)
    model.write_object(0x607D, 1, -3600)
    model.write_object(0x607D, 2, 3600)
    # 補正後の上限 = 3600 - 1000 = 2600。原点復帰で現在位置は 1000 になっている
    run(model, 3000)
    assert model.read_object(0x6064) <= 2600 + 50


def test_limit_sensor_stops_the_motor_and_sets_ila():
    model = pv_model(target=200)
    run(model, 500)
    assert abs(model.read_object(0x606C)) > 100
    model.set_limit_inputs(fw_ls=True)
    run(model, 500)
    assert abs(model.read_object(0x606C)) < 2
    assert model.read_object(0x6041) & SW_ILA


def test_limit_sensor_allows_moving_away():
    model = pv_model(target=200)
    model.set_limit_inputs(fw_ls=True)
    run(model, 200)
    assert abs(model.read_object(0x606C)) < 2
    model.write_object(0x60FF, 0, -200)   # 反対方向は許す
    run(model, 500)
    assert model.read_object(0x606C) < -50


def test_digital_inputs_report_the_limit_sensors():
    model = pv_model()
    model.set_limit_inputs(fw_ls=True, rv_ls=True, home=True)
    run(model, 2)
    value = model.read_object(0x60FD)
    assert value & (1 << 0)   # NLS (RV-LS)
    assert value & (1 << 1)   # PLS (FW-LS)
    assert value & (1 << 2)   # HS  (HOMES)


def test_internal_limit_is_cleared_once_free_again():
    model = pv_model(target=200)
    model.set_limit_inputs(fw_ls=True)
    run(model, 100)
    assert model.read_object(0x6041) & SW_ILA
    model.set_limit_inputs(fw_ls=False)
    run(model, 100)
    assert model.read_object(0x6041) & SW_ILA == 0
