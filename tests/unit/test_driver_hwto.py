"""HWTO と DriverModel の結合。仕様は HP-5141J 4 章 / HP-5143E 6.2・60FDh 実測。"""
import pytest

from omsim.driver.alarm_model import EMCY_HWTO_CIRCUIT, EMCY_HWTO_DETECTED
from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import MODE_PV, DriverModel


def enabled_model(target_rpm=100):
    model = DriverModel(node_id=1)
    model.step(0.001)
    model.write_object(0x6060, 0, MODE_PV)
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    model.write_object(0x60FF, 0, target_rpm)
    for _ in range(500):
        model.step(0.001)
    assert model.state_machine.state == "operation-enabled"
    assert abs(model.actual_velocity_rpm - target_rpm) < 5
    return model


def run(model, milliseconds):
    for _ in range(milliseconds):
        model.step(0.001)


def test_hwto1_off_stops_the_motor_by_free_run():
    """安全リレー断 = HWTO1 OFF。無励磁になりフリーランで止まる (実機の挙動)。"""
    model = enabled_model()
    model.set_hwto_inputs(False, True)
    run(model, 500)
    assert model.power_cut is True
    assert model.state_machine.state == "switch-on-disabled"
    assert abs(model.actual_velocity_rpm) < 1.0


def test_brake_is_engaged_while_power_is_cut():
    model = enabled_model()
    model.set_hwto_inputs(False, True)
    run(model, 50)
    assert model.brake_engaged is True


def test_brake_is_released_again_once_inputs_return_and_the_drive_is_enabled():
    model = enabled_model()
    model.set_hwto_inputs(False, True)
    run(model, 50)
    model.set_hwto_inputs(True, True)
    run(model, 10)
    assert model.power_cut is False
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    run(model, 10)
    assert model.state_machine.state == "operation-enabled"
    assert model.brake_engaged is False


def test_single_channel_cut_does_not_need_eto_clear_to_recover():
    """片系配線 (実機) では ETO 状態に入らないので、入力復帰＋再 enable で戻れる。"""
    model = enabled_model()
    model.set_hwto_inputs(False, True)
    run(model, 50)
    assert model.hwto.eto_active is False
    model.set_hwto_inputs(True, True)
    run(model, 10)
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    assert model.state_machine.state == "operation-enabled"


def test_both_channels_cut_requires_clear_eto():
    """標準の 2 重系配線で両方 OFF になると「動力遮断+ETO 状態」。40D0h で解除する。"""
    model = enabled_model()
    model.set_hwto_inputs(False, False)
    run(model, 50)
    assert model.hwto.eto_active is True

    model.set_hwto_inputs(True, True)
    run(model, 10)
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    assert model.state_machine.state != "operation-enabled"  # ETO 解除がまだ

    model.write_object(0x40D0, 0, 1)
    run(model, 10)
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    assert model.state_machine.state == "operation-enabled"


def test_clear_eto_is_rejected_while_inputs_are_still_off():
    model = enabled_model()
    model.set_hwto_inputs(False, False)
    run(model, 50)
    with pytest.raises(ObjectAccessError):
        model.write_object(0x40D0, 0, 1)


def test_digital_inputs_bit3_reflects_hwto_status():
    """60FDh bit3: どちらかの HWTO 入力が active なら 1 (HP-5143E 実測)。"""
    model = enabled_model()
    assert model.read_object(0x60FD) & (1 << 3) == 0
    model.set_hwto_inputs(False, True)
    run(model, 10)
    assert model.read_object(0x60FD) & (1 << 3) == (1 << 3)


def test_detection_alarm_is_raised_when_the_parameter_is_enabled():
    model = DriverModel(node_id=1)
    model.hwto.alarm_on_off_input = True
    model.step(0.001)
    model.set_hwto_inputs(False, True)
    run(model, 20)
    assert model.alarms.is_active
    assert model.alarms.error_code == EMCY_HWTO_DETECTED


def test_circuit_alarm_is_raised_after_the_mismatch_delay():
    model = DriverModel(node_id=1)
    model.hwto.dual_mismatch_delay_ms = 50
    model.step(0.001)
    model.set_hwto_inputs(False, True)
    run(model, 100)
    assert model.alarms.is_active
    assert model.alarms.error_code == EMCY_HWTO_CIRCUIT


def test_no_alarm_with_the_factory_defaults_on_single_channel_wiring():
    """既定値 (どちらのパラメータも無効) では、片系 OFF でもアラームは出ない。

    実機がこの配線で成立している理由をテストで固定する。
    """
    model = enabled_model()
    model.set_hwto_inputs(False, True)
    run(model, 1000)
    assert not model.alarms.is_active


def test_snapshot_exposes_hwto_state_for_the_web():
    model = enabled_model()
    model.set_hwto_inputs(False, True)
    run(model, 10)
    snapshot = model.snapshot()
    assert snapshot["power_cut"] is True
    assert snapshot["brake_engaged"] is True
    assert snapshot["hwto"] == {
        "hwto1_on": False, "hwto2_on": True,
        "eto_active": False, "edm_mon": False, "hwtoin_mon": True,
    }


def test_validate_object_does_not_clear_eto_on_the_real_model():
    """40D0h の検証 (SDO 受信時) が実モデルの ETO を解除してしまわないこと。

    validate_object は writer を使い捨てコピー上で走らせる方式なので、
    writer が触る入れ子は _SHADOW_DEEP_ATTRS に入っていなければならない。
    hwto が漏れていると、SDO で 40D0h=1 を書いた瞬間 (キューに積む前の
    検証段階) に実モデルの ETO が解除される。
    """
    model = enabled_model()
    model.set_hwto_inputs(False, False)
    run(model, 50)
    model.set_hwto_inputs(True, True)
    run(model, 10)
    assert model.hwto.eto_active is True

    model.validate_object(0x40D0, 0, 1)
    assert model.hwto.eto_active is True  # 検証だけでは解除されない
