"""HWTO (動力遮断機能) のモデル。仕様は HP-5141J 4 章 p204-212 実測。"""
from omsim.driver.hwto import HwtoModel

MS = 0.001


def run(model, hwto1_on, hwto2_on, milliseconds):
    for _ in range(milliseconds):
        model.set_inputs(hwto1_on, hwto2_on, MS)


def test_both_inputs_on_is_normal():
    model = HwtoModel()
    run(model, True, True, 50)
    assert model.power_cut is False
    assert model.eto_active is False
    assert model.hwtoin_mon is False
    assert model.edm_mon is False
    assert model.pending_alarm is None


def test_single_input_off_cuts_power_but_is_not_eto():
    """HWTO1 OFF は上アーム遮断。トルクは出せないが「動力遮断+ETO 状態」ではない。"""
    model = HwtoModel()
    run(model, True, True, 10)
    run(model, False, True, 50)
    assert model.power_cut is True
    assert model.eto_active is False
    assert model.hwtoin_mon is True     # どちらか OFF で ON
    assert model.edm_mon is False       # 両方 OFF のときだけ ON


def test_both_inputs_off_enters_eto():
    model = HwtoModel()
    run(model, True, True, 10)
    run(model, False, False, 50)
    assert model.power_cut is True
    assert model.eto_active is True
    assert model.eto_mon is True
    assert model.edm_mon is True


def test_one_millisecond_offshot_pulse_is_ignored():
    """外部機器の自己診断パルス (1ms 以下) では動力遮断機能は動作しない。"""
    model = HwtoModel()
    run(model, True, True, 10)
    run(model, False, False, 1)   # 1ms だけ OFF
    run(model, True, True, 10)
    assert model.power_cut is False
    assert model.eto_active is False


def test_longer_pulse_does_cut_power():
    model = HwtoModel()
    run(model, True, True, 10)
    run(model, False, False, 3)
    assert model.power_cut is True


def test_dual_mismatch_alarm_is_disabled_by_default():
    """「HWTO-2重系異常検出遅延時間」の初期値 0 は無効。片系配線でも 53h は出ない。"""
    model = HwtoModel()
    run(model, True, True, 10)
    run(model, False, True, 500)
    assert model.pending_alarm is None


def test_dual_mismatch_alarm_after_the_configured_delay():
    model = HwtoModel(dual_mismatch_delay_ms=50)
    run(model, True, True, 10)
    run(model, False, True, 40)
    assert model.pending_alarm is None
    run(model, False, True, 20)   # 合計 60ms > 50ms
    assert model.pending_alarm == "circuit"


def test_no_mismatch_alarm_when_the_other_input_turns_off_in_time():
    model = HwtoModel(dual_mismatch_delay_ms=50)
    run(model, True, True, 10)
    run(model, False, True, 30)
    run(model, False, False, 100)
    assert model.pending_alarm is None


def test_detection_alarm_only_when_enabled():
    disabled = HwtoModel(alarm_on_off_input=False)
    run(disabled, True, True, 10)
    run(disabled, False, False, 20)
    assert disabled.pending_alarm is None

    enabled = HwtoModel(alarm_on_off_input=True)
    run(enabled, True, True, 10)
    run(enabled, False, False, 20)
    assert enabled.pending_alarm == "detected"


def test_eto_is_not_cleared_just_by_turning_the_inputs_back_on():
    model = HwtoModel()
    run(model, True, True, 10)
    run(model, False, False, 20)
    run(model, True, True, 20)
    assert model.power_cut is False     # 入力が戻れば遮断自体は解ける
    assert model.eto_active is True     # ETO 状態は残る


def test_clear_eto_requires_both_inputs_on():
    model = HwtoModel()
    run(model, True, True, 10)
    run(model, False, False, 20)
    assert model.clear_eto() is False   # まだ両方 OFF
    run(model, True, True, 20)
    assert model.clear_eto() is True
    assert model.eto_active is False


def test_take_pending_alarm_clears_it():
    model = HwtoModel(alarm_on_off_input=True)
    run(model, True, True, 10)
    run(model, False, False, 20)
    assert model.take_pending_alarm() == "detected"
    assert model.take_pending_alarm() is None
