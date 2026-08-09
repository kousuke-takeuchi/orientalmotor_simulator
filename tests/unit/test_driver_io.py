"""リモート I/O。HP-5143E 60FDh/60FEh/403Eh/403Fh 実測。

R-IN0..15  = S-ON / PLOOP-MODE / TRQ-LMT / CLR / QSTOP / STOP / FREE / ALM-RST /
             D-SEL0..7
R-OUT0..15 = SON-MON / PLOOP-MON / TRQ-LMTD / RDY-DD-OPE / ABSPEN / STOP_R /
             FREE_R / ALM-A / SYS-BSY / IN-POS / RDY-HOME-OPE / RDY-FWRV-OPE /
             RDY-SD-OPE / MOVE / VA / TLC
60FEh:01 の bit16-31 が R-IN、60FDh の bit16-31 が R-OUT。
"""
from omsim.driver.model import MODE_PV, DriverModel

R_IN_BASE = 16
R_OUT_BASE = 16

RIN_S_ON = R_IN_BASE + 0
RIN_QSTOP = R_IN_BASE + 4
RIN_STOP = R_IN_BASE + 5
RIN_FREE = R_IN_BASE + 6

ROUT_SON_MON = R_OUT_BASE + 0
ROUT_ALM_A = R_OUT_BASE + 7
ROUT_MOVE = R_OUT_BASE + 13
ROUT_TLC = R_OUT_BASE + 15


def enabled_model(target=200):
    model = DriverModel(node_id=1)
    model.step(0.001)
    model.write_object(0x6060, 0, MODE_PV)
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    model.write_object(0x60FF, 0, target)
    return model


def run(model, milliseconds):
    for _ in range(milliseconds):
        model.step(0.001)


def test_digital_outputs_default_to_zero():
    model = DriverModel(node_id=1)
    assert model.read_object(0x60FE, 1) == 0


def test_remote_input_bits_are_readable_back():
    model = DriverModel(node_id=1)
    model.write_object(0x60FE, 1, 1 << RIN_STOP)
    assert model.read_object(0x60FE, 1) == 1 << RIN_STOP
    assert model.read_object(0x403E) == 1 << RIN_STOP


def test_driver_input_command_and_digital_outputs_are_the_same_register():
    model = DriverModel(node_id=1)
    model.write_object(0x403E, 0, 1 << RIN_FREE)
    assert model.read_object(0x60FE, 1) == 1 << RIN_FREE


def test_son_mon_follows_excitation():
    model = enabled_model()
    run(model, 5)
    assert model.read_object(0x403F) & (1 << ROUT_SON_MON)
    model.write_object(0x6040, 0, 0x0006)
    run(model, 5)
    assert model.read_object(0x403F) & (1 << ROUT_SON_MON) == 0


def test_move_output_is_on_while_running():
    model = enabled_model()
    run(model, 300)
    assert model.read_object(0x403F) & (1 << ROUT_MOVE)
    model.write_object(0x60FF, 0, 0)
    run(model, 800)
    assert model.read_object(0x403F) & (1 << ROUT_MOVE) == 0


def test_alarm_output_follows_the_alarm_state():
    model = enabled_model()
    run(model, 5)
    assert model.read_object(0x403F) & (1 << ROUT_ALM_A) == 0
    model.inject_alarm(0x30, 0x2310)
    run(model, 5)
    assert model.read_object(0x403F) & (1 << ROUT_ALM_A)


def test_free_input_removes_excitation():
    model = enabled_model()
    run(model, 300)
    model.write_object(0x403E, 0, 1 << RIN_FREE)
    run(model, 300)
    assert model.plant.excited is False
    assert abs(model.read_object(0x606C)) < 2


def test_stop_input_stops_the_motor_but_keeps_excitation():
    model = enabled_model()
    run(model, 300)
    model.write_object(0x403E, 0, 1 << RIN_STOP)
    run(model, 500)
    assert abs(model.read_object(0x606C)) < 2
    assert model.plant.excited is True


def test_qstop_input_triggers_quick_stop():
    model = enabled_model()
    run(model, 300)
    model.write_object(0x403E, 0, 1 << RIN_QSTOP)
    run(model, 500)
    assert model.state_machine.state in ("quick-stop-active", "switch-on-disabled")
    assert abs(model.read_object(0x606C)) < 2


def test_stop_input_sets_internal_limit_active():
    """STOP / QSTOP / CLR は Statusword bit11 を立てる (HP-5143E 7.3.4 実測)。"""
    model = enabled_model()
    run(model, 100)
    model.write_object(0x403E, 0, 1 << RIN_STOP)
    run(model, 10)
    assert model.read_object(0x6041) & (1 << 11)


def test_digital_outputs_is_no_longer_a_stub():
    model = DriverModel(node_id=1)
    keys = set((index, sub) for index, sub, _reason in model.stub_objects())
    assert (0x60FE, 1) not in keys
