import pytest

from omsim.driver.motor_plant import MotorPlant
from omsim.driver.operation import (
    OperationContext,
    OperationMode,
    ProfileVelocityMode,
)
from omsim.driver.profile import TrapezoidProfile
from omsim.driver.state_machine import Cia402StateMachine
from omsim.driver.units import UnitConverter


class Params(object):
    def __init__(self):
        self.target_velocity_rpm = 0.0
        self.profile_acceleration_rpm_s = 1000.0
        self.profile_deceleration_rpm_s = 1000.0
        self.velocity_window_rpm = 1.0
        self.velocity_threshold_rpm = 1.0

    @property
    def effective_deceleration_rpm_s(self):
        # DriverModel と同じ窓口。ここでは quick stop の切替を持たない。
        return self.profile_deceleration_rpm_s


def make_context():
    return OperationContext(
        state_machine=Cia402StateMachine(),
        profile=TrapezoidProfile(),
        plant=MotorPlant(),
        units=UnitConverter(),
        params=Params(),
    )


def enable(ctx):
    ctx.state_machine.step(0.001)
    ctx.state_machine.write_controlword(0x0006)
    ctx.state_machine.write_controlword(0x0007)
    ctx.state_machine.write_controlword(0x000F)
    ctx.plant.excited = True


def test_pv_mode_code_is_three():
    assert ProfileVelocityMode().mode_code == 3


def test_base_class_requires_subclasses_to_implement_step():
    ctx = make_context()
    with pytest.raises(NotImplementedError):
        OperationMode().step(0.001, ctx)


def test_pv_drives_the_profile_towards_the_target():
    ctx = make_context()
    enable(ctx)
    mode = ProfileVelocityMode()
    ctx.params.target_velocity_rpm = 100.0
    ctx.params.profile_acceleration_rpm_s = 6000.0
    for _ in range(3000):
        mode.step(0.001, ctx)
    assert abs(ctx.units.internal_to_rpm(ctx.plant.velocity) - 100.0) <= 1.0


def test_pv_holds_zero_while_not_excited():
    ctx = make_context()
    mode = ProfileVelocityMode()
    ctx.params.target_velocity_rpm = 100.0
    for _ in range(1000):
        mode.step(0.001, ctx)
    assert ctx.plant.velocity == 0.0


def test_pv_sets_target_reached_when_settled():
    ctx = make_context()
    enable(ctx)
    mode = ProfileVelocityMode()
    ctx.params.target_velocity_rpm = 100.0
    ctx.params.profile_acceleration_rpm_s = 6000.0
    ctx.params.profile_deceleration_rpm_s = 6000.0
    ctx.params.velocity_window_rpm = 2.0
    for _ in range(3000):
        mode.step(0.001, ctx)
        mode.apply_status_bits(ctx)
    assert ctx.state_machine.target_reached is True


def test_pv_sets_bit12_when_stopped():
    ctx = make_context()
    enable(ctx)
    mode = ProfileVelocityMode()
    ctx.params.target_velocity_rpm = 0.0
    mode.step(0.001, ctx)
    mode.apply_status_bits(ctx)
    assert ctx.state_machine.operation_mode_specific_12 is True


def test_pv_clears_bit12_while_running():
    ctx = make_context()
    enable(ctx)
    mode = ProfileVelocityMode()
    ctx.params.target_velocity_rpm = 100.0
    ctx.params.profile_acceleration_rpm_s = 6000.0
    for _ in range(3000):
        mode.step(0.001, ctx)
        mode.apply_status_bits(ctx)
    assert ctx.state_machine.operation_mode_specific_12 is False


def test_two_modes_do_not_share_state():
    a, b = ProfileVelocityMode(), ProfileVelocityMode()
    assert a is not b
    assert a.mode_code == b.mode_code
