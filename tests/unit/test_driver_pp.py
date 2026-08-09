"""pp (Profile Position) モード。HP-5143E 7.3 実測。

Controlword: bit4 NSP / bit5 IMM / bit6 REL / bit8 HALT
Statusword : bit10 TR / bit12 SPA / bit13 Following error
"""
import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import MODE_PP, DriverModel

CW_ENABLE = 0x000F
CW_NSP = 1 << 4
CW_IMM = 1 << 5
CW_REL = 1 << 6
CW_HALT = 1 << 8

SW_TR = 1 << 10
SW_SPA = 1 << 12


def pp_model(profile_velocity=300, accel=6000, decel=6000):
    model = DriverModel(node_id=1)
    model.step(0.001)
    model.write_object(0x6060, 0, MODE_PP)
    model.write_object(0x6081, 0, profile_velocity)
    model.write_object(0x6083, 0, accel)
    model.write_object(0x6084, 0, decel)
    for controlword in (0x0006, 0x0007, CW_ENABLE):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    return model


def run(model, milliseconds):
    for _ in range(milliseconds):
        model.step(0.001)


def start_move(model, target, extra_bits=0):
    model.write_object(0x607A, 0, target)
    model.write_object(0x6040, 0, CW_ENABLE | extra_bits)            # NSP=0
    model.step(0.001)
    model.write_object(0x6040, 0, CW_ENABLE | CW_NSP | extra_bits)   # NSP 0->1
    model.step(0.001)


def test_mode_display_reports_pp():
    model = pp_model()
    assert model.read_object(0x6061) == MODE_PP


def test_absolute_positioning_reaches_the_target():
    model = pp_model()
    start_move(model, 18000)   # 3600 inc/rev なので 5 回転
    run(model, 4000)
    assert abs(model.read_object(0x6064) - 18000) <= 20
    assert model.read_object(0x6041) & SW_TR


def test_target_reached_is_low_while_moving():
    model = pp_model()
    start_move(model, 36000)
    run(model, 50)
    assert model.read_object(0x6041) & SW_TR == 0


def test_set_point_acknowledge_handshake():
    model = pp_model()
    assert model.read_object(0x6041) & SW_SPA == 0
    start_move(model, 36000)
    assert model.read_object(0x6041) & SW_SPA        # 受理した
    run(model, 4000)
    assert model.read_object(0x6041) & SW_SPA == 0   # 完了して次を待てる


def test_relative_positioning_moves_by_the_distance():
    model = pp_model()
    start_move(model, 7200)
    run(model, 3000)
    first = model.read_object(0x6064)
    start_move(model, 7200, extra_bits=CW_REL)
    run(model, 3000)
    assert abs(model.read_object(0x6064) - (first + 7200)) <= 20


def test_negative_target_moves_backwards():
    model = pp_model()
    start_move(model, -7200)
    run(model, 3000)
    assert abs(model.read_object(0x6064) + 7200) <= 20


def test_change_set_immediately_replaces_the_running_move():
    model = pp_model()
    start_move(model, 360000)      # 100 回転。長い移動
    run(model, 100)
    start_move(model, 3600, extra_bits=CW_IMM)   # 途中で 1 回転へ差し替え
    run(model, 4000)
    assert abs(model.read_object(0x6064) - 3600) <= 30


def test_set_of_set_points_waits_for_the_current_move():
    """IMM=0 で運転中に NSP を立てると、現在の位置決め完了後に開始する。"""
    model = pp_model()
    start_move(model, 7200)
    run(model, 50)
    start_move(model, 14400)       # IMM=0。保持されるはず
    run(model, 100)
    # まだ 1 つ目の目標 (7200) を目指している
    assert model.read_object(0x6064) < 7200
    run(model, 6000)
    assert abs(model.read_object(0x6064) - 14400) <= 30


def test_halt_stops_the_move_and_sets_target_reached():
    model = pp_model()
    start_move(model, 360000)
    run(model, 100)
    moving_position = model.read_object(0x6064)
    model.write_object(0x6040, 0, CW_ENABLE | CW_HALT)
    run(model, 500)
    stopped = model.read_object(0x6064)
    assert stopped > moving_position          # 減速して止まった
    assert abs(model.read_object(0x606C)) < 2
    assert model.read_object(0x6041) & SW_TR  # HALT=1 のときは「停止した」の意味
    run(model, 200)
    assert abs(model.read_object(0x6064) - stopped) <= 5


def test_end_velocity_is_rejected_when_non_zero():
    """6082h End velocity は 0 以外未対応。黙って 0 として動かさない。"""
    model = pp_model()
    assert model.read_object(0x6082) == 0
    with pytest.raises(ObjectAccessError):
        model.write_object(0x6082, 0, 100)


def test_positioning_option_code_rejects_unsupported_options():
    """60F2h の Change immediately / Request-response / IP option は仕様上未サポート。"""
    model = pp_model()
    assert model.read_object(0x60F2) == 0
    with pytest.raises(ObjectAccessError):
        model.write_object(0x60F2, 0, 1 << 2)   # Change immediately option
    with pytest.raises(ObjectAccessError):
        model.write_object(0x60F2, 0, 1 << 8)   # IP option


def test_profile_velocity_is_no_longer_a_stub():
    model = DriverModel(node_id=1)
    keys = set((index, sub) for index, sub, _reason in model.stub_objects())
    assert (0x6081, 0) not in keys
    assert (0x607A, 0) not in keys
