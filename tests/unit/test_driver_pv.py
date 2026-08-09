import pytest

from omsim.driver.errors import (
    ABORT_DEVICE_STATE,
    NotImplementedObjectError,
    ObjectAccessError,
)
from omsim.driver.model import MODE_PV, DriverModel
from omsim.driver.state_machine import State

SHUTDOWN = 0x0006
SWITCH_ON = 0x0007
ENABLE_OPERATION = 0x000F


def enabled_model(**kwargs):
    model = DriverModel(node_id=1, **kwargs)
    model.step(0.001)
    model.write_object(0x6060, 0, MODE_PV)
    model.write_object(0x6040, 0, SHUTDOWN)
    model.write_object(0x6040, 0, SWITCH_ON)
    model.write_object(0x6040, 0, ENABLE_OPERATION)
    return model


def run(model, seconds):
    for _ in range(int(round(seconds / 0.001))):
        model.step(0.001)


def test_mode_display_follows_mode_of_operation():
    model = enabled_model()
    assert model.read_object(0x6061) == MODE_PV


def test_unsupported_mode_is_reported_as_not_implemented():
    model = DriverModel(node_id=1)
    with pytest.raises(NotImplementedObjectError) as exc:
        model.write_object(0x6060, 0, 1)
    # NotImplementedObjectError は ObjectAccessError のサブクラスなので
    # od_bridge.py の SDO abort への変換対象に入る（生の NotImplementedError
    # は変換対象外で汎用 abort に潰れ、メッセージが消えていた）。
    assert isinstance(exc.value, ObjectAccessError)
    assert exc.value.abort_code == ABORT_DEVICE_STATE
    assert "1" in str(exc.value)


def test_statusword_shows_operation_enabled():
    model = enabled_model()
    assert model.read_object(0x6041) & 0x6F == 0x27
    assert model.state_machine.state == State.OPERATION_ENABLED


def test_motor_is_excited_only_in_operation_enabled():
    model = enabled_model()
    assert model.plant.excited is True
    model.write_object(0x6040, 0, SWITCH_ON)
    model.step(0.001)
    assert model.plant.excited is False


def test_does_not_move_before_operation_enabled():
    model = DriverModel(node_id=1)
    model.step(0.001)
    model.write_object(0x6060, 0, MODE_PV)
    model.write_object(0x60FF, 0, 100)
    run(model, 1.0)
    assert model.read_object(0x606C) == 0
    assert model.read_object(0x6064) == 0


def test_reaches_target_velocity_in_rpm():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    model.write_object(0x60FF, 0, 100)
    run(model, 3.0)
    assert abs(model.read_object(0x606C) - 100) <= 1


def test_velocity_demand_follows_the_acceleration_ramp():
    model = enabled_model()
    model.write_object(0x6083, 0, 100)  # 100 r/min/s
    model.write_object(0x60FF, 0, 100)
    run(model, 0.5)
    demand = model.read_object(0x606B)
    assert 40 <= demand <= 60


def test_position_advances_while_running_forward():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x60FF, 0, 100)
    run(model, 1.0)
    assert model.read_object(0x6064) > 0


def test_negative_target_runs_in_reverse():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    model.write_object(0x60FF, 0, -100)
    run(model, 3.0)
    assert abs(model.read_object(0x606C) + 100) <= 1
    assert model.read_object(0x6064) < 0


def test_target_reached_bit_sets_when_settled():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    model.write_object(0x606D, 0, 2)  # velocity window 2 r/min
    model.write_object(0x60FF, 0, 100)
    run(model, 3.0)
    assert model.read_object(0x6041) & (1 << 10)


def test_target_reached_bit_clears_while_accelerating():
    model = enabled_model()
    model.write_object(0x6083, 0, 10)
    model.write_object(0x606D, 0, 2)
    model.write_object(0x60FF, 0, 3000)
    run(model, 0.2)
    assert not model.read_object(0x6041) & (1 << 10)


def test_gear_ratio_changes_the_position_scale():
    slow = enabled_model()
    slow.write_object(0x6091, 1, 1)
    slow.write_object(0x6091, 2, 1)
    slow.write_object(0x6083, 0, 6000)
    slow.write_object(0x60FF, 0, 60)
    run(slow, 2.0)

    geared = enabled_model()
    geared.write_object(0x6091, 1, 100)
    geared.write_object(0x6091, 2, 1)
    geared.write_object(0x6083, 0, 6000)
    geared.write_object(0x60FF, 0, 60)
    run(geared, 2.0)

    assert geared.read_object(0x6064) > slow.read_object(0x6064) * 50


def test_torque_actual_value_is_readable():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x60FF, 0, 100)
    run(model, 1.0)
    assert isinstance(model.read_object(0x6077), int)


def test_supported_drive_modes_advertises_pv():
    model = DriverModel(node_id=1)
    assert model.read_object(0x6502) & (1 << 2)


def test_statusword_is_read_only():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError):
        model.write_object(0x6041, 0, 0)


def test_alarm_drops_the_state_machine_into_fault():
    model = enabled_model()
    model.inject_alarm(0x30, 0x2310)
    model.step(0.001)
    model.step(0.001)
    assert model.read_object(0x6041) & 0x4F == 0x08
    assert model.read_object(0x603F) == 0x2310
    assert model.read_object(0x1001) != 0


def test_alarm_stops_the_motor():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x60FF, 0, 100)
    run(model, 1.0)
    model.inject_alarm(0x30, 0x2310)
    run(model, 1.0)
    assert abs(model.read_object(0x606C)) <= 1


def test_alarm_reset_via_40c0_raises_while_cause_persists():
    # 修正2: 原因が解消していない間は 40C0h への書き込みが SDO 成功を装って
    # 何もしない、という嘘を止める。ObjectAccessError で abort させる。
    model = enabled_model()
    model.inject_alarm(0x30, 0x2310)
    run(model, 0.01)
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x40C0, 0, 1)
    assert exc.value.abort_code == ABORT_DEVICE_STATE
    # Fault から抜けられていないことも確認する。
    assert model.read_object(0x6041) & 0x4F == 0x08
    assert model.read_object(0x603F) == 0x2310


def test_alarm_reset_via_40c0_clears_the_fault():
    # 「2 段階で復帰する」(40C0h でアラーム解除 -> 6040h Fault reset の
    # 立ち上がりで switch-on-disabled へ) という検証内容自体は維持する。
    # 原因の解消は公開 API の clear_alarm_cause() を経由するように変更した。
    model = enabled_model()
    model.inject_alarm(0x30, 0x2310)
    run(model, 0.01)
    model.clear_alarm_cause()
    model.write_object(0x40C0, 0, 1)
    model.write_object(0x6040, 0, 0x0000)
    model.write_object(0x6040, 0, 0x0080)
    model.step(0.001)
    assert model.read_object(0x6041) & 0x4F == 0x40
    assert model.read_object(0x603F) == 0


def test_snapshot_exposes_the_monitor_values():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x60FF, 0, 100)
    run(model, 2.0)
    snap = model.snapshot()
    assert snap["node_id"] == 1
    assert snap["mode"] == MODE_PV
    assert snap["state"] == State.OPERATION_ENABLED
    assert abs(snap["target_velocity_rpm"] - 100) < 1e-9
    assert abs(snap["actual_velocity_rpm"] - 100) <= 1
    assert "statusword" in snap
    assert "actual_position" in snap
    assert "torque_permille" in snap
    assert snap["alarm"] is None
    assert snap["alarm_history"] == []


def test_speed_bit_is_set_while_stopped():
    model = enabled_model()
    model.step(0.001)
    assert model.read_object(0x6041) & (1 << 12)


def test_speed_bit_clears_while_running_at_target():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    model.write_object(0x60FF, 0, 100)
    run(model, 3.0)
    assert not model.read_object(0x6041) & (1 << 12)


def test_speed_bit_reflects_velocity_threshold():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    model.write_object(0x60FF, 0, 100)
    run(model, 3.0)
    assert not model.read_object(0x6041) & (1 << 12)

    model.write_object(0x606F, 0, 200)  # 606Fh Velocity threshold = 200 r/min
    model.step(0.001)
    assert model.read_object(0x6041) & (1 << 12)


def test_two_models_run_at_different_speeds():
    a = enabled_model()
    b = enabled_model()
    for model, target in ((a, 100), (b, 50)):
        model.write_object(0x6083, 0, 6000)
        model.write_object(0x6084, 0, 6000)
        model.write_object(0x60FF, 0, target)
    for _ in range(3000):
        a.step(0.001)
        b.step(0.001)
    assert abs(a.read_object(0x606C) - 100) <= 1
    assert abs(b.read_object(0x606C) - 50) <= 1


# --- 修正4: Quick stop (605Ah) の既定挙動 (Transition 12) ---

def test_quick_stop_ramps_down_and_exits_to_switch_on_disabled():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    model.write_object(0x60FF, 0, 100)
    run(model, 1.0)
    assert abs(model.read_object(0x606C) - 100) <= 1

    model.write_object(0x6040, 0, 0x0002)  # Quick stop
    model.step(0.001)
    assert model.state_machine.state == State.QUICK_STOP_ACTIVE

    run(model, 5.0)
    assert model.state_machine.state == State.SWITCH_ON_DISABLED
    assert abs(model.read_object(0x606C)) <= 1


def test_quick_stop_option_code_is_stubbed():
    keys = set((index, sub) for index, sub, _reason in DriverModel.router.stubs())
    assert (0x605A, 0) in keys


def test_torque_limit_objects_are_stubbed():
    keys = set((index, sub) for index, sub, _reason in DriverModel.router.stubs())
    assert (0x6072, 0) in keys
    assert (0x4032, 0) in keys


def test_nmt_reset_is_stubbed():
    keys = set((index, sub) for index, sub, _reason in DriverModel.router.stubs())
    assert (0x0000, 0x81) in keys


# --- 修正: step() 内の profile.reset(0.0) の呼び出し位置 ---
#
# pv を OperationMode へ分離した際、profile.reset(0.0) の判定が
# self.operation.step(dt, ctx) の後ろへ移ってしまった。reset(0.0) の設計
# 意図は「減速ランプを経由せずに指令を即座にゼロにする」ことであり、この
# 順序では FAULT に突入した最初の 1 ステップで reset される前に profile が
# 1 回進み、その (減速ランプ中の) 指令値で plant.step() が呼ばれてしまう。
#
# 606Ch (実速度) や 606Bh を step() の後で読んでも、この 1 ステップ限りの
# 差は MotorPlant が非励磁時に command_velocity 引数そのものを無視する
# ため観測できない (excited=False なら target は常に 0 に強制される)。
# そのため plant.step() の呼び出し引数そのものをスパイして検証する。
def test_fault_zeroes_the_command_immediately_without_ramping():
    model = enabled_model()
    model.write_object(0x6083, 0, 6000)  # 100 r/min/s よりずっと緩い加減速
    model.write_object(0x6084, 0, 6000)
    model.write_object(0x60FF, 0, 3000)
    run(model, 3.0)
    assert abs(model.read_object(0x606C) - 3000) <= 5  # 前提: 高速で回っている

    seen_commands = []
    original_step = model.plant.step

    def spy_step(dt, command_velocity):
        seen_commands.append(command_velocity)
        return original_step(dt, command_velocity)

    model.plant.step = spy_step

    model.inject_alarm(0x30, 0x2310)
    model.step(0.001)

    # FAULT に落ちた最初の 1 ステップで、plant に渡る指令はランプ値では
    # なく即座に 0.0 でなければならない (profile.reset(0.0) の意味づけ)。
    assert seen_commands == [0.0]
    assert model.state_machine.state == State.FAULT
