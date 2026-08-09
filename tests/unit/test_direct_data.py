"""ダイレクトデータ運転。HP-5141J 4 章 / HP-5143E 402Ch-4034h 実測。

4033h: 上位16bit = ライフタイム、下位16bit = 反映トリガ
  0: 起動しない / 1(2,3): 通常起動 (ユーザー単位) / 4-19: 単位指定起動
  同じ値の再書き込みでは起動しない。トリガ自動クリア (既定有効) で 0 に戻る。
"""
import pytest

from omsim.driver.errors import NotImplementedObjectError, ObjectAccessError
from omsim.driver.model import DriverModel

CW_ENABLE = 0x000F

TYPE_ABS = 1
TYPE_REL_COMMAND = 2
TYPE_CONTINUOUS_VELOCITY = 16
TYPE_DECEL_STOP = 0
TYPE_IMMEDIATE_STOP = 32


def excited_model():
    model = DriverModel(node_id=1)
    model.step(0.001)
    for controlword in (0x0006, 0x0007, CW_ENABLE):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    model.write_object(0x4030, 0, 6000)   # 加速レート
    model.write_object(0x4031, 0, 6000)   # 減速レート
    return model


def run(model, milliseconds):
    for _ in range(milliseconds):
        model.step(0.001)


def trigger(model, value=1):
    model.write_object(0x4033, 0, value)
    model.step(0.001)


def test_defaults():
    model = DriverModel(node_id=1)
    assert model.read_object(0x402C) == 0
    assert model.read_object(0x402D) == 0
    assert model.read_object(0x402E) == 0
    assert model.read_object(0x4033) == 0


def test_unsupported_operation_type_is_rejected():
    model = excited_model()
    with pytest.raises(NotImplementedObjectError):
        model.write_object(0x402D, 0, 7)      # 連続運転 (位置制御) は未実装


def test_operation_type_outside_the_table_is_rejected():
    model = excited_model()
    with pytest.raises(ObjectAccessError):
        model.write_object(0x402D, 0, 24)


def test_trigger_zero_does_not_start():
    model = excited_model()
    model.write_object(0x402D, 0, TYPE_CONTINUOUS_VELOCITY)
    model.write_object(0x402F, 0, 200)
    trigger(model, 0)
    run(model, 200)
    assert abs(model.read_object(0x606C)) < 1


def test_continuous_velocity_runs_at_the_given_speed():
    model = excited_model()
    model.write_object(0x402D, 0, TYPE_CONTINUOUS_VELOCITY)
    model.write_object(0x402F, 0, 200)
    trigger(model)
    run(model, 500)
    assert abs(model.read_object(0x606C) - 200) < 5


def test_absolute_positioning_moves_to_the_position():
    model = excited_model()
    model.write_object(0x402D, 0, TYPE_ABS)
    model.write_object(0x402E, 0, 7200)
    model.write_object(0x402F, 0, 300)
    trigger(model)
    run(model, 4000)
    assert abs(model.read_object(0x6064) - 7200) <= 30


def test_relative_positioning_adds_to_the_command_position():
    model = excited_model()
    model.write_object(0x402D, 0, TYPE_ABS)
    model.write_object(0x402E, 0, 3600)
    model.write_object(0x402F, 0, 300)
    trigger(model)
    run(model, 3000)

    model.write_object(0x402D, 0, TYPE_REL_COMMAND)
    model.write_object(0x402E, 0, 3600)
    trigger(model, 2)     # 別の値なので再度起動する
    run(model, 3000)
    assert abs(model.read_object(0x6064) - 7200) <= 40


def test_writing_the_same_trigger_value_does_not_restart():
    """同じ値を書いた場合は起動しない (HP-5141J 4-3 実測)。"""
    model = excited_model()
    model.write_object(0x402D, 0, TYPE_CONTINUOUS_VELOCITY)
    model.write_object(0x402F, 0, 100)
    trigger(model, 1)
    run(model, 300)
    model.write_object(0x402F, 0, 300)   # 速度だけ書き換え
    trigger(model, 1)                     # 同じ値
    run(model, 500)
    assert abs(model.read_object(0x606C) - 100) < 5   # 100 のまま


def test_trigger_is_auto_cleared_by_default():
    model = excited_model()
    model.write_object(0x402D, 0, TYPE_CONTINUOUS_VELOCITY)
    model.write_object(0x402F, 0, 100)
    trigger(model, 1)
    assert model.read_object(0x4033) & 0xFFFF == 0


def test_lifetime_is_kept_in_the_upper_half():
    model = excited_model()
    model.write_object(0x4033, 0, (0x1234 << 16) | 1)
    model.step(0.001)
    assert model.direct_data_lifetime == 0x1234


def test_out_of_range_trigger_does_not_apply_either_half():
    """どちらかが範囲外なら上位・下位とも反映しない (HP-5141J 4-3 実測)。"""
    model = excited_model()
    model.write_object(0x4033, 0, (0x1111 << 16) | 1)
    model.step(0.001)
    before_lifetime = model.direct_data_lifetime
    with pytest.raises(ObjectAccessError):
        model.write_object(0x4033, 0, (0x2222 << 16) | 20)   # 下位が範囲外
    assert model.direct_data_lifetime == before_lifetime


def test_negative_trigger_is_reported_as_not_implemented():
    """個別項目トリガ (-1〜-7) は未実装。黙って通常起動にしない。"""
    model = excited_model()
    with pytest.raises(NotImplementedObjectError):
        model.write_object(0x4033, 0, -4)


def test_deceleration_stop_type_stops_the_motor():
    model = excited_model()
    model.write_object(0x402D, 0, TYPE_CONTINUOUS_VELOCITY)
    model.write_object(0x402F, 0, 200)
    trigger(model, 1)
    run(model, 500)
    model.write_object(0x402D, 0, TYPE_DECEL_STOP)
    trigger(model, 2)
    run(model, 500)
    assert abs(model.read_object(0x606C)) < 2


def test_immediate_stop_type_stops_at_once():
    model = excited_model()
    model.write_object(0x402D, 0, TYPE_CONTINUOUS_VELOCITY)
    model.write_object(0x402F, 0, 200)
    trigger(model, 1)
    run(model, 500)
    model.write_object(0x402D, 0, TYPE_IMMEDIATE_STOP)
    trigger(model, 2)
    run(model, 3)
    assert abs(model.read_object(0x606C)) < 1


def test_direct_data_does_not_start_without_excitation():
    """運転には S-ON (励磁) が必要 (HP-5141J 4 章冒頭)。"""
    model = DriverModel(node_id=1)
    model.step(0.001)
    model.write_object(0x402D, 0, TYPE_CONTINUOUS_VELOCITY)
    model.write_object(0x402F, 0, 200)
    trigger(model, 1)
    run(model, 300)
    assert abs(model.read_object(0x606C)) < 1


def test_torque_limit_object_is_applied_as_a_ceiling():
    model = excited_model()
    model.write_object(0x4032, 0, 50)
    assert model.direct_torque_limit_permille == 50


def test_validate_object_does_not_consume_the_trigger():
    """4033h の検証 (SDO 受信時) が実モデルのトリガ状態を変えないこと。

    write_trigger は「同じ値なら起動しない」ために直近値を覚える副作用が
    あるので、_SHADOW_DEEP_ATTRS に direct_data が入っていないと、
    検証だけで直近値が更新されて本番の起動が消える。
    """
    model = excited_model()
    model.write_object(0x402D, 0, TYPE_CONTINUOUS_VELOCITY)
    model.write_object(0x402F, 0, 200)
    model.validate_object(0x4033, 0, 1)   # 検証だけ
    trigger(model, 1)                      # 本番の書き込み
    run(model, 500)
    assert abs(model.read_object(0x606C) - 200) < 5


def test_direct_data_runs_through_the_real_sdo_path():
    """CAN 受信スレッドと同じ経路 (validate -> queue -> drain) で起動すること。

    3 つの書込みが同じ 1ms に届く実運用の形。加減速レートを既定 (1000) の
    ままにすると、CiA402 の運転モードと指令を奪い合っていた欠陥がここで出る。
    """
    from omsim.sim.command_queue import CommandQueue

    model = DriverModel(node_id=1)
    model.step(0.001)
    for controlword in (0x0006, 0x0007, CW_ENABLE):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)

    queue = CommandQueue()
    for index, sub, value in ((0x402D, 0, TYPE_CONTINUOUS_VELOCITY),
                              (0x402F, 0, 150),
                              (0x4033, 0, 1)):
        model.validate_object(index, sub, value)
        queue.put(index, sub, value)
    for _ in range(500):
        queue.drain(model)
        model.step(0.001)
    assert abs(model.read_object(0x606C) - 150) < 5
