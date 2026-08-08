from omsim.driver.alarm_model import ALARM_OVERLOAD, EMCY_OVERLOAD, AlarmModel


def test_starts_clean():
    model = AlarmModel()
    assert model.is_active is False
    assert model.active_alarm is None
    assert model.error_code == 0
    assert model.error_register == 0
    assert model.history == []


def test_raising_sets_active_alarm_and_codes():
    model = AlarmModel()
    model.raise_alarm(ALARM_OVERLOAD, EMCY_OVERLOAD, error_register=0x21)
    assert model.is_active is True
    assert model.active_alarm == ALARM_OVERLOAD
    assert model.error_code == EMCY_OVERLOAD
    assert model.error_register == 0x21


def test_raising_queues_an_emcy():
    model = AlarmModel()
    model.raise_alarm(ALARM_OVERLOAD, EMCY_OVERLOAD, error_register=0x21)
    assert model.pop_pending_emcy() == (EMCY_OVERLOAD, 0x21)
    assert model.pop_pending_emcy() is None


def test_raising_appends_to_history_newest_first():
    model = AlarmModel()
    model.raise_alarm(0x30, 0x2310)
    model.set_cause_cleared(True)
    model.reset()
    model.raise_alarm(0x31, 0x2311)
    assert model.history[0] == 0x31
    assert model.history[1] == 0x30


def test_history_is_bounded():
    model = AlarmModel(history_size=3)
    for code in range(0x30, 0x38):
        model.raise_alarm(code, 0x2310)
        model.set_cause_cleared(True)
        model.reset()
    assert len(model.history) == 3


def test_reset_fails_while_cause_persists():
    model = AlarmModel()
    model.raise_alarm(ALARM_OVERLOAD, EMCY_OVERLOAD)
    assert model.reset() is False
    assert model.is_active is True


def test_reset_succeeds_after_cause_cleared():
    model = AlarmModel()
    model.raise_alarm(ALARM_OVERLOAD, EMCY_OVERLOAD)
    model.set_cause_cleared(True)
    assert model.reset() is True
    assert model.is_active is False
    assert model.error_code == 0
    assert model.error_register == 0


def test_reset_queues_an_error_reset_emcy():
    model = AlarmModel()
    model.raise_alarm(ALARM_OVERLOAD, EMCY_OVERLOAD)
    model.pop_pending_emcy()
    model.set_cause_cleared(True)
    model.reset()
    assert model.pop_pending_emcy() == (0x0000, 0x00)


def test_reset_on_clean_model_is_a_no_op():
    model = AlarmModel()
    assert model.reset() is True
    assert model.pop_pending_emcy() is None


def test_second_alarm_while_active_is_ignored():
    model = AlarmModel()
    model.raise_alarm(0x30, 0x2310)
    model.raise_alarm(0x31, 0x2311)
    assert model.active_alarm == 0x30
    assert model.history == [0x30]


def test_clear_history_empties_the_list_but_keeps_active_alarm():
    model = AlarmModel()
    model.raise_alarm(0x30, 0x2310)
    model.clear_history()
    assert model.history == []
    assert model.active_alarm == 0x30


def test_two_models_are_independent():
    a, b = AlarmModel(), AlarmModel()
    a.raise_alarm(0x30, 0x2310)
    assert b.is_active is False
    assert b.history == []
