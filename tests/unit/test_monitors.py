"""モニタ系オブジェクトとメンテナンスコマンド。HP-5143E 実測。"""
import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import MODE_PV, DriverModel


def running_model(target=120):
    model = DriverModel(node_id=1)
    model.step(0.001)
    model.write_object(0x6060, 0, MODE_PV)
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    model.write_object(0x60FF, 0, target)
    for _ in range(500):
        model.step(0.001)
    return model


def run(model, milliseconds):
    for _ in range(milliseconds):
        model.step(0.001)


# --- ユーザー単位モニタ (404Bh-4050h) ---

def test_user_unit_monitors_mirror_the_standard_objects():
    model = running_model()
    assert model.read_object(0x404D) == model.read_object(0x6064)   # 実位置
    assert model.read_object(0x4050) == model.read_object(0x606C)   # 実速度
    assert model.read_object(0x404F) == model.read_object(0x606B)   # 指令速度
    assert model.read_object(0x404E) == model.read_object(0x60FF)   # 目標速度
    assert model.read_object(0x404B) == model.read_object(0x607A)   # 目標位置


def test_demand_position_follows_the_actual_position_in_pv():
    model = running_model()
    assert abs(model.read_object(0x404C) - model.read_object(0x6064)) <= 2


# --- 偏差 (4073h / 4075h) ---

def test_position_and_speed_deviation_are_small_while_settled():
    model = running_model()
    run(model, 500)
    assert abs(model.read_object(0x4075)) <= 2


def test_speed_deviation_is_visible_during_acceleration():
    model = DriverModel(node_id=1)
    model.step(0.001)
    model.write_object(0x6083, 0, 60000)
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    model.write_object(0x60FF, 0, 300)
    run(model, 10)
    assert abs(model.read_object(0x4075)) > 5


# --- 負荷率 (406Bh / 406Ch / 4078h) ---

def test_torque_monitor_matches_the_torque_object():
    model = running_model()
    assert model.read_object(0x406B) == model.read_object(0x6077)


def test_load_factor_is_derived_from_the_torque():
    model = running_model()
    model.plant.torque_permille = 500
    assert model.read_object(0x406C) == 500


def test_overload_factor_is_relative_to_the_max_torque():
    model = running_model()
    model.write_object(0x6072, 0, 1000)
    model.plant.torque_permille = 500
    # 過負荷率 = 実トルク / 最大トルク の百分率
    assert model.read_object(0x4078) == 50


# --- 稼働時間・距離 (40A1h / 40A9h / 407Eh / 407Fh) ---

def test_uptime_counts_simulated_seconds():
    model = running_model()
    run(model, 2000)
    assert model.read_object(0x40A1) >= 2
    assert model.read_object(0x40A9) >= 2


def test_odometer_counts_travelled_revolutions():
    model = running_model(target=600)
    run(model, 3000)
    # 600 r/min で 3 秒 = 30 回転前後
    assert model.read_object(0x407E) >= 20


def test_tripmeter_can_be_cleared():
    model = running_model(target=600)
    run(model, 2000)
    assert model.read_object(0x407F) > 0
    model.write_object(0x40D7, 0, 1)
    assert model.read_object(0x407F) == 0


def test_odometer_is_not_cleared_by_the_tripmeter_command():
    model = running_model(target=600)
    run(model, 2000)
    odometer = model.read_object(0x407E)
    model.write_object(0x40D7, 0, 1)
    assert model.read_object(0x407E) == odometer


# --- メンテナンスコマンド ---

def test_p_preset_sets_the_current_position_to_the_home_offset():
    model = running_model()
    model.write_object(0x607C, 0, 500)
    model.write_object(0x40C5, 0, 1)
    assert model.read_object(0x6064) == 500


def test_clear_alarm_history_empties_1003h():
    model = running_model()
    model.inject_alarm(0x30)
    assert model.read_object(0x1003, 0) == 1
    model.write_object(0x40C2, 0, 1)
    assert model.read_object(0x1003, 0) == 0


def test_maintenance_commands_read_back_zero():
    model = running_model()
    for index in (0x40C2, 0x40C5, 0x40D6, 0x40D7, 0x40D8):
        assert model.read_object(index) == 0


def test_writing_zero_to_a_maintenance_command_does_nothing():
    model = running_model(target=600)
    run(model, 2000)
    before = model.read_object(0x407F)
    model.write_object(0x40D7, 0, 0)
    assert model.read_object(0x407F) == before


# --- モデルが持っていない量はスタブとして明示する ---

@pytest.mark.parametrize("index", [0x407C, 0x407D, 0x40A3, 0x40A4, 0x409C])
def test_unmodelled_quantities_are_registered_as_stubs(index):
    model = DriverModel(node_id=1)
    keys = set((idx, sub) for idx, sub, _reason in model.stub_objects())
    assert (index, 0) in keys
    assert model.read_object(index) == 0
