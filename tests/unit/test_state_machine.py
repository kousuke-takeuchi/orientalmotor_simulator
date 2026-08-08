from omsim.driver.state_machine import Cia402StateMachine, State

SHUTDOWN = 0x0006
SWITCH_ON = 0x0007
ENABLE_OPERATION = 0x000F
DISABLE_VOLTAGE = 0x0000
QUICK_STOP = 0x0002
FAULT_RESET = 0x0080


def enabled_machine():
    sm = Cia402StateMachine()
    sm.write_controlword(SHUTDOWN)
    sm.write_controlword(SWITCH_ON)
    sm.write_controlword(ENABLE_OPERATION)
    return sm


def test_starts_in_switch_on_disabled_after_first_step():
    sm = Cia402StateMachine()
    sm.step(0.001)
    assert sm.state == State.SWITCH_ON_DISABLED
    assert sm.statusword & 0x4F == 0x40


def test_shutdown_moves_to_ready_to_switch_on():
    sm = Cia402StateMachine()
    sm.write_controlword(SHUTDOWN)
    assert sm.state == State.READY_TO_SWITCH_ON
    assert sm.statusword & 0x6F == 0x21


def test_switch_on_moves_to_switched_on():
    sm = Cia402StateMachine()
    sm.write_controlword(SHUTDOWN)
    sm.write_controlword(SWITCH_ON)
    assert sm.state == State.SWITCHED_ON
    assert sm.statusword & 0x6F == 0x23


def test_enable_operation_moves_to_operation_enabled():
    sm = enabled_machine()
    assert sm.state == State.OPERATION_ENABLED
    assert sm.statusword & 0x6F == 0x27
    assert sm.is_operation_enabled is True


def test_quick_stop_moves_to_quick_stop_active():
    sm = enabled_machine()
    sm.write_controlword(QUICK_STOP)
    assert sm.state == State.QUICK_STOP_ACTIVE
    assert sm.statusword & 0x6F == 0x07


def test_disable_voltage_returns_to_switch_on_disabled():
    sm = enabled_machine()
    sm.write_controlword(DISABLE_VOLTAGE)
    assert sm.state == State.SWITCH_ON_DISABLED


def test_disable_operation_returns_to_switched_on():
    sm = enabled_machine()
    sm.write_controlword(SWITCH_ON)
    assert sm.state == State.SWITCHED_ON
    assert sm.is_operation_enabled is False


def test_fault_enters_fault_reaction_then_fault():
    sm = enabled_machine()
    sm.set_fault(True)
    assert sm.state == State.FAULT_REACTION_ACTIVE
    assert sm.statusword & 0x4F == 0x0F
    sm.step(0.001)
    assert sm.state == State.FAULT
    assert sm.statusword & 0x4F == 0x08


def test_fault_reset_requires_rising_edge_of_bit7():
    sm = enabled_machine()
    sm.set_fault(True)
    sm.step(0.001)
    sm.write_controlword(FAULT_RESET)
    assert sm.state == State.FAULT
    sm.set_fault(False)
    sm.write_controlword(0x0000)
    sm.write_controlword(FAULT_RESET)
    assert sm.state == State.SWITCH_ON_DISABLED


def test_fault_reset_does_nothing_while_cause_persists():
    sm = enabled_machine()
    sm.set_fault(True)
    sm.step(0.001)
    sm.write_controlword(0x0000)
    sm.write_controlword(FAULT_RESET)
    assert sm.state == State.FAULT


def test_statusword_reflects_flag_bits():
    sm = enabled_machine()
    sm.target_reached = True
    sm.internal_limit_active = True
    sm.warning = True
    assert sm.statusword & (1 << 10)
    assert sm.statusword & (1 << 11)
    assert sm.statusword & (1 << 7)
    assert sm.statusword & (1 << 4)  # voltage enabled は既定 True


def test_operation_mode_specific_12_reflects_in_statusword():
    # HP-5143E 7.2.4 (p39): pv での bit12 (SPD) は速度 0 かどうか。
    # ステートマシン自体は意味を知らず、外から設定された値をそのまま bit12
    # に反映するだけ。
    sm = enabled_machine()
    assert sm.statusword & (1 << 12) == 0
    sm.operation_mode_specific_12 = True
    assert sm.statusword & (1 << 12)
    sm.operation_mode_specific_12 = False
    assert sm.statusword & (1 << 12) == 0


def test_voltage_disabled_drops_out_of_operation():
    sm = enabled_machine()
    sm.voltage_enabled = False
    sm.step(0.001)
    assert sm.state == State.SWITCH_ON_DISABLED


def test_quick_stop_from_ready_to_switch_on_moves_to_switch_on_disabled():
    # HP-5143E 6 (p34) コマンド表: Quick Stop は Transition 7, 10, 11 を起こす。
    # 6.2 (p35) Transition 7: ready-to-switch-on -> switch-on-disabled
    sm = Cia402StateMachine()
    sm.write_controlword(SHUTDOWN)
    assert sm.state == State.READY_TO_SWITCH_ON
    sm.write_controlword(QUICK_STOP)
    assert sm.state == State.SWITCH_ON_DISABLED


def test_quick_stop_active_ignores_repeated_quick_stop_command():
    # Quick Stop の遷移元表 (HP-5143E 6, p34: Transitions 7, 10, 11) に
    # quick-stop-active は含まれないため、状態は変化しない。
    sm = enabled_machine()
    sm.write_controlword(QUICK_STOP)
    assert sm.state == State.QUICK_STOP_ACTIVE
    sm.write_controlword(QUICK_STOP)
    assert sm.state == State.QUICK_STOP_ACTIVE


def test_quick_stop_from_switched_on_moves_to_switch_on_disabled():
    # HP-5143E 6 (p34) コマンド表 / 6.2 (p35) Transition 10:
    # switched-on -> switch-on-disabled (Disable Voltage または Quick Stop)。
    sm = enabled_machine()
    sm.write_controlword(SWITCH_ON)
    assert sm.state == State.SWITCHED_ON
    sm.write_controlword(QUICK_STOP)
    assert sm.state == State.SWITCH_ON_DISABLED


def test_stop_completed_transitions_quick_stop_active_to_switch_on_disabled():
    sm = enabled_machine()
    sm.write_controlword(QUICK_STOP)
    assert sm.state == State.QUICK_STOP_ACTIVE
    sm.stop_completed()
    assert sm.state == State.SWITCH_ON_DISABLED


def test_stop_completed_is_a_noop_outside_quick_stop_active():
    sm = enabled_machine()
    sm.stop_completed()
    assert sm.state == State.OPERATION_ENABLED


def test_two_machines_are_independent():
    a, b = enabled_machine(), Cia402StateMachine()
    b.step(0.001)
    assert a.state == State.OPERATION_ENABLED
    assert b.state == State.SWITCH_ON_DISABLED
