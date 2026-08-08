"""BLVD-KRD ドライバの挙動モデル。can / canopen を import しないこと。

参照: HP-5143E 7.2 Profile Velocity Mode (p37)、HP-5141J 第1章 (p12-48)
"""
from omsim.driver.alarm_model import AlarmModel
from omsim.driver.errors import ABORT_VALUE_RANGE, ObjectAccessError
from omsim.driver.motor_plant import MotorPlant
from omsim.driver.objects import ObjectRouter
from omsim.driver.profile import TrapezoidProfile
from omsim.driver.state_machine import Cia402StateMachine, State
from omsim.driver.units import UnitConverter

MODE_PV = 3
MODE_PP = 1
MODE_TQ = 4
MODE_HM = 6

# 6502h Supported drive modes: bit0=pp, bit2=pv, bit3=tq, bit5=hm
SUPPORTED_DRIVE_MODES = (1 << 0) | (1 << 2) | (1 << 3) | (1 << 5)

_INT32_MIN, _INT32_MAX = -(2 ** 31), 2 ** 31 - 1


def _clamp_int32(value):
    return max(_INT32_MIN, min(_INT32_MAX, int(value)))


class DriverModel(object):
    """1 台のドライバ。状態は全てインスタンス変数に持つ。"""

    router = ObjectRouter()

    DEVICE_NAME = "BLVD-KRD"

    def __init__(self, node_id, time_constant=0.02, load_torque_permille=0.0):
        self.node_id = node_id
        self.sim_time = 0.0

        self.state_machine = Cia402StateMachine()
        self.units = UnitConverter()
        self.profile = TrapezoidProfile()
        self.plant = MotorPlant(
            time_constant=time_constant, load_torque_permille=load_torque_permille
        )
        self.alarms = AlarmModel()

        self.mode = MODE_PV
        self.target_velocity_rpm = 0.0
        self.profile_acceleration_rpm_s = 1000.0
        self.profile_deceleration_rpm_s = 1000.0
        self.velocity_window_rpm = 1.0
        self.velocity_threshold_rpm = 1.0
        self.max_torque_permille = 10000
        self.digital_outputs = 0
        self.profile_velocity_rpm = 1
        self.consumer_heartbeat_config = 0

    # --- 外向きの窓口は以下の 4 つだけ ---

    def read_object(self, index, sub=0):
        return self.router.read(self, index, sub)

    def write_object(self, index, sub=0, value=0):
        self.router.write(self, index, sub, value)

    def step(self, dt):
        self.sim_time += dt

        if self.alarms.is_active:
            self.state_machine.set_fault(True)
        self.state_machine.step(dt)

        excited = self._sync_excited()

        self.profile.acceleration = self.units.rpm_to_internal(
            self.profile_acceleration_rpm_s)
        self.profile.deceleration = self.units.rpm_to_internal(
            self.profile_deceleration_rpm_s)

        if excited:
            self.profile.set_target(self.units.rpm_to_internal(self.target_velocity_rpm))
        else:
            self.profile.set_target(0.0)
            if self.state_machine.state in (State.FAULT, State.SWITCH_ON_DISABLED):
                self.profile.reset(0.0)

        self.profile.step(dt)
        self.plant.step(dt, self.profile.command)

        error_rpm = abs(self.actual_velocity_rpm - self.command_velocity_rpm)
        self.state_machine.target_reached = (
            excited and self.profile.at_target and error_rpm <= self.velocity_window_rpm
        )

        # HP-5143E 7.2.4 (p39): pv モードでの Statusword bit12 (SPD) は
        # 「速度が 0 かどうか」= 実速度の絶対値が Velocity threshold (606Fh)
        # 以下かどうか。
        if self.mode == MODE_PV:
            self.state_machine.operation_mode_specific_12 = (
                abs(self.actual_velocity_rpm) <= self.velocity_threshold_rpm
            )

    def _sync_excited(self):
        """励磁状態 (plant.excited) をステートマシンの現在の状態から同期する。

        write_controlword() は state を同期的に遷移させるため、step() を
        待たずに励磁状態も同期する必要がある（次の step() 呼び出し前に励磁
        を観測するテストのため）。step() と _write_controlword() の両方
        から呼ばれる共通処理。
        """
        excited = self.state_machine.is_operation_enabled
        self.plant.excited = excited
        return excited

    def snapshot(self):
        return {
            "node_id": self.node_id,
            "sim_time": self.sim_time,
            "state": self.state_machine.state,
            "statusword": self.state_machine.statusword,
            "mode": self.mode,
            "target_velocity_rpm": self.target_velocity_rpm,
            "command_velocity_rpm": self.command_velocity_rpm,
            "actual_velocity_rpm": self.actual_velocity_rpm,
            "actual_position": self.plant.position,
            "torque_permille": self.plant.torque_permille,
            "alarm": self.alarms.active_alarm,
            "alarm_history": self.alarms.history,
        }

    # --- テストと Web からアラームを注入する口 ---

    def inject_alarm(self, alarm_code, emcy_code, error_register=0x21):
        self.alarms.raise_alarm(alarm_code, emcy_code, error_register)

    # --- 派生値 ---

    @property
    def command_velocity_rpm(self):
        return self.units.internal_to_rpm(self.profile.command)

    @property
    def actual_velocity_rpm(self):
        return self.units.internal_to_rpm(self.plant.velocity)

    # --- 通信オブジェクト ---

    @router.reader(0x1001)
    def _read_error_register(self, sub):
        return self.alarms.error_register

    @router.reader(0x1008)
    def _read_device_name(self, sub):
        return self.DEVICE_NAME

    @router.reader(0x603F)
    def _read_error_code(self, sub):
        return self.alarms.error_code

    # --- CiA402 ---

    @router.reader(0x6040)
    def _read_controlword(self, sub):
        return self.state_machine.controlword

    @router.writer(0x6040)
    def _write_controlword(self, sub, value):
        self.state_machine.write_controlword(int(value) & 0xFFFF)
        self._sync_excited()

    @router.reader(0x6041)
    def _read_statusword(self, sub):
        return self.state_machine.statusword

    @router.reader(0x6060)
    def _read_mode(self, sub):
        return self.mode

    @router.writer(0x6060)
    def _write_mode(self, sub, value):
        mode = int(value)
        if mode != MODE_PV:
            raise NotImplementedError(
                "運転モード {} は P4 で実装する (6060h)".format(mode))
        self.mode = mode

    @router.reader(0x6061)
    def _read_mode_display(self, sub):
        return self.mode

    @router.reader(0x6064)
    def _read_position_actual(self, sub):
        return _clamp_int32(self.plant.position)

    @router.reader(0x606B)
    def _read_velocity_demand(self, sub):
        return _clamp_int32(round(self.command_velocity_rpm))

    @router.reader(0x606C)
    def _read_velocity_actual(self, sub):
        return _clamp_int32(round(self.actual_velocity_rpm))

    @router.reader(0x606D)
    def _read_velocity_window(self, sub):
        return int(self.velocity_window_rpm)

    @router.writer(0x606D)
    def _write_velocity_window(self, sub, value):
        if int(value) < 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "606Dh は 0 以上")
        self.velocity_window_rpm = float(value)

    @router.reader(0x606F)
    def _read_velocity_threshold(self, sub):
        return int(self.velocity_threshold_rpm)

    @router.writer(0x606F)
    def _write_velocity_threshold(self, sub, value):
        if int(value) < 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "606Fh は 0 以上")
        self.velocity_threshold_rpm = float(value)

    @router.reader(0x6077)
    def _read_torque_actual(self, sub):
        return _clamp_int32(round(self.plant.torque_permille))

    @router.reader(0x6072)
    def _read_max_torque(self, sub):
        return self.max_torque_permille

    @router.writer(0x6072)
    def _write_max_torque(self, sub, value):
        # EDS: LowLimit=0 HighLimit=10000 (千分率、1000 = 定格トルク)
        if not (0 <= int(value) <= 10000):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6072h は 0-10000")
        self.max_torque_permille = int(value)

    @router.reader(0x60FE, 1)
    def _read_digital_outputs(self, sub):
        return self.digital_outputs

    @router.writer(0x60FE, 1)
    def _write_digital_outputs(self, sub, value):
        self.digital_outputs = int(value) & 0xFFFFFFFF

    @router.reader(0x1003, 0)
    def _read_error_field_count(self, sub):
        return len(self.alarms.history)

    @router.writer(0x1003, 0)
    def _write_error_field_count(self, sub, value):
        # CiA301: sub0 に 0 を書くとエラー履歴 (sub1..) をクリアする。
        if int(value) != 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "1003h sub0 は 0 のみ書き込み可")
        self.alarms.clear_history()

    def _read_error_field(self, sub):
        history = self.alarms.history
        if sub < 1 or sub > len(history):
            return 0
        return history[sub - 1]

    for _sub in range(1, 11):
        router.reader(0x1003, _sub)(_read_error_field)
    del _sub

    # --- メーカ固有 (pitakuru motor_control_node が実際に触れているもののみ) ---

    @router.reader(0x4032)
    def _read_direct_torque_limit(self, sub):
        return self.max_torque_permille

    @router.writer(0x4032)
    def _write_direct_torque_limit(self, sub, value):
        # EDS: LowLimit 記載無し。6072h と同じ千分率レンジとして扱う。
        if not (0 <= int(value) <= 10000):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "4032h は 0-10000")
        self.max_torque_permille = int(value)

    @router.reader(0x409B)
    def _read_main_power_current(self, sub):
        # 実測未対応。0 [mA] を返すだけの最小実装 (P6 でアラーム/電流モデルと統合)。
        return 0

    @router.reader(0x6081)
    def _read_profile_velocity(self, sub):
        return int(self.profile_velocity_rpm)

    @router.writer(0x6081)
    def _write_profile_velocity(self, sub, value):
        if int(value) < 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6081h は 0 以上")
        self.profile_velocity_rpm = int(value)

    @router.reader(0x1016, 1)
    def _read_consumer_heartbeat_time(self, sub):
        return self.consumer_heartbeat_config

    @router.writer(0x1016, 1)
    def _write_consumer_heartbeat_time(self, sub, value):
        # PDO/Heartbeat consumer 自体は P3 まで未実装。値の保持のみ行う。
        self.consumer_heartbeat_config = int(value) & 0xFFFFFFFF

    @router.reader(0x6083)
    def _read_profile_acceleration(self, sub):
        return int(self.profile_acceleration_rpm_s)

    @router.writer(0x6083)
    def _write_profile_acceleration(self, sub, value):
        if int(value) <= 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6083h は 1 以上")
        self.profile_acceleration_rpm_s = float(value)

    @router.reader(0x6084)
    def _read_profile_deceleration(self, sub):
        return int(self.profile_deceleration_rpm_s)

    @router.writer(0x6084)
    def _write_profile_deceleration(self, sub, value):
        if int(value) <= 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6084h は 1 以上")
        self.profile_deceleration_rpm_s = float(value)

    @router.reader(0x608F, 1)
    def _read_encoder_increments(self, sub):
        return self.units.encoder_increments

    @router.writer(0x608F, 1)
    def _write_encoder_increments(self, sub, value):
        self.units.set_encoder_resolution(int(value), self.units.motor_revolutions)

    @router.reader(0x608F, 2)
    def _read_encoder_motor_revolutions(self, sub):
        return self.units.motor_revolutions

    @router.writer(0x608F, 2)
    def _write_encoder_motor_revolutions(self, sub, value):
        self.units.set_encoder_resolution(self.units.encoder_increments, int(value))

    @router.reader(0x6091, 1)
    def _read_gear_motor_revolutions(self, sub):
        return self.units.gear_motor_revolutions

    @router.writer(0x6091, 1)
    def _write_gear_motor_revolutions(self, sub, value):
        self.units.set_gear_ratio(int(value), self.units.gear_shaft_revolutions)

    @router.reader(0x6091, 2)
    def _read_gear_shaft_revolutions(self, sub):
        return self.units.gear_shaft_revolutions

    @router.writer(0x6091, 2)
    def _write_gear_shaft_revolutions(self, sub, value):
        self.units.set_gear_ratio(self.units.gear_motor_revolutions, int(value))

    @router.reader(0x60FF)
    def _read_target_velocity(self, sub):
        return _clamp_int32(round(self.target_velocity_rpm))

    @router.writer(0x60FF)
    def _write_target_velocity(self, sub, value):
        self.target_velocity_rpm = float(int(value))

    @router.reader(0x6502)
    def _read_supported_drive_modes(self, sub):
        return SUPPORTED_DRIVE_MODES

    # --- メーカ固有 ---

    @router.writer(0x40C0)
    def _write_alarm_reset(self, sub, value):
        if int(value):
            self.alarms.reset()
            if not self.alarms.is_active:
                self.state_machine.set_fault(False)
