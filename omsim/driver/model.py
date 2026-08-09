"""BLVD-KRD ドライバの挙動モデル。can / canopen を import しないこと。

参照: HP-5143E 7.2 Profile Velocity Mode (p37)、HP-5141J 第1章 (p12-48)
"""
import copy

from omsim.driver.alarm_model import (
    ALARM_HWTO_CIRCUIT,
    ALARM_HWTO_DETECTED,
    EMCY_HEARTBEAT_ERROR,
    EMCY_HWTO_CIRCUIT,
    EMCY_HWTO_DETECTED,
    ERROR_REGISTER_HWTO,
    AlarmModel,
)
from omsim.driver.hwto import HwtoModel  # noqa: I100 (driver 層内の依存)
from omsim.driver.direct_data import DirectDataState
from omsim.driver.errors import (
    ABORT_DEVICE_STATE,
    ABORT_NO_DATA,
    ABORT_VALUE_RANGE,
    NotImplementedObjectError,
    ObjectAccessError,
)
from omsim.driver.motor_plant import MotorPlant
from omsim.driver.objects import ObjectRouter
from omsim.driver.operation_type import resolve_operation_type
from omsim.driver.operation import (
    HomingMode,
    OperationContext,
    ProfilePositionMode,
    ProfileTorqueMode,
    ProfileVelocityMode,
)
from omsim.driver.pdo import (
    RPDO_BASE_COB_ID,
    RPDO_TRANSMISSION_TYPES,
    TPDO_BASE_COB_ID,
    MappingEntry,
    PdoCommParams,
    PdoMappingParams,
    is_supported_tpdo_transmission_type,
    pack_mapping_entry,
    unpack_mapping_entry,
)
from omsim.driver.profile import TrapezoidProfile
from omsim.driver.state_machine import Cia402StateMachine, State
from omsim.driver.stopping import (
    IMMEDIATE,
    QUICK_STOP_RAMP,
    resolve_disable_operation,
    resolve_fault_reaction,
    resolve_halt,
    resolve_quick_stop,
    resolve_shutdown,
)
from omsim.driver.units import UnitConverter

MODE_PV = ProfileVelocityMode.MODE_CODE
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

    _SHUTDOWN_OPTION_STUB_REASON = (
        "P4: 605Bh は値の保持のみ。operation-enabled -> ready-to-switch-on の"
        "遷移は常に即時停止 (= 既定値 0 の挙動) で、1 (slow down ramp) にしても"
        "挙動は変わらない"
    )
    _DISABLE_OPERATION_OPTION_STUB_REASON = (
        "P4: 605Ch は値の保持のみ。operation-enabled -> switched-on の遷移は"
        "常に即時停止で、既定値 1 (slow down ramp) の挙動になっていない"
    )
    _FAULT_REACTION_OPTION_STUB_REASON = (
        "P4: 605Eh は値の保持のみ。アラーム検出時の停止は常に即時停止で、"
        "既定値 2 (6085h のランプで減速) の挙動になっていない"
    )

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
        self.operation = ProfileVelocityMode()
        self.target_velocity_rpm = 0.0
        self.profile_acceleration_rpm_s = 1000.0
        self.profile_deceleration_rpm_s = 1000.0
        self.velocity_window_rpm = 1.0
        self.velocity_threshold_rpm = 1.0
        # 6072h Max torque（CiA402 標準）と 4032h Direct data operation
        # torque limiting value（メーカ固有、ダイレクトデータ運転専用）は
        # EDS 上も別オブジェクトであり、HP-5141J 第1章4節「トルク制限機能」
        # の通り複数のトルク制限ソースが独立に存在し最小値で動作する設計。
        # よって別々のインスタンス変数として保持する（共有しない）。
        self.max_torque_permille = 10000
        self.direct_torque_limit_permille = 10000
        self.digital_outputs = 0
        self.profile_velocity_rpm = 1
        # hm (Homing) 用。既定値は EDS 実測 (6098h=37 / 6099h=60,30 / 609Ah=1000)
        self.homing_method = 37
        self.homing_speed_switch_rpm = 60
        self.homing_speed_zero_rpm = 30
        self.homing_acceleration_rpm_s = 1000
        self.home_offset = 0
        self.homing_completed = False
        # CN4 のリミット/HOME センサ入力 (実配線は P5)
        self.limit_inputs = {"fw_ls": False, "rv_ls": False, "home": False}
        # ダイレクトデータ運転 (402Ch-4034h)。CiA402 の運転モードとは独立。
        self.direct_data = DirectDataState()
        # 実行中のダイレクトデータ運転 (None なら CiA402 モードが動く)
        self._direct_motion = None

        # touch probe (60B8h-60BDh / 60D5h-60D8h)。既定 3131h は EDS 実測。
        self.touch_probe_function = 0x3131
        # probe -> {"positive": 値 or None, "negative": ..., カウンタ}
        self.touch_probe_values = {
            1: {"positive": None, "negative": None},
            2: {"positive": None, "negative": None},
        }
        self.touch_probe_counters = {
            1: {"positive": 0, "negative": 0},
            2: {"positive": 0, "negative": 0},
        }

        # 607Dh Software position limit
        self.software_min_position = 0
        self.software_max_position = 0

        # tq (Profile Torque) 用
        self.target_torque = 0
        self.torque_slope = 0
        # pp (Profile Position) 用
        self.target_position = 0
        self.end_velocity = 0
        self.positioning_option_code = 0
        self.consumer_heartbeat_config = 0
        self.producer_heartbeat_config = 0
        # 停止動作の option code (HP-5143E 605Ah-605Eh 実測の既定値)。
        self.quick_stop_option_code = 2
        self.shutdown_option_code = 0
        self.disable_operation_option_code = 1
        self.halt_option_code = 1
        self.fault_reaction_option_code = 2
        # 6085h Quick stop deceleration。既定は通常の減速度と同じにしておく。
        self.quick_stop_deceleration_rpm_s = 1000.0

        # PDO 通信パラメータ (1400h-1403h / 1800h-1803h)。既定値は EDS 実測。
        self.rpdo_comm = [
            PdoCommParams(cob_id=RPDO_BASE_COB_ID[i] + node_id, valid=True,
                          rtr_allowed=True, transmission_type=255)
            for i in range(4)
        ]
        self.tpdo_comm = [
            PdoCommParams(cob_id=TPDO_BASE_COB_ID[i] + node_id, valid=True,
                          rtr_allowed=False,
                          transmission_type=(255 if i < 2 else 1),
                          inhibit_time_100us=50, event_timer_ms=0)
            for i in range(4)
        ]

        # HWTO (動力遮断機能)。入力は CN4 の配線経由で set_hwto_inputs() から入る。
        # 既定は「両方 ON」= 動力遮断が働いていない状態。
        self.hwto = HwtoModel()

        # node guarding (100Ch/100Dh)。生死判定は NMT master 側の責務のため
        # (4.2.1 実測)、スレーブ側は値の保持と RTR 応答のみ行う。
        self.guard_time_ms = 0
        self.life_time_factor = 0
        # Heartbeat consumer (1016h sub1)
        self.heartbeat_consumer_node_id = 0
        self.heartbeat_consumer_time_ms = 0
        self._heartbeat_consumer_reference_time = None

        # 1005h COB-ID SYNC message。producer/consumer の詳細実装は Task 10。
        self.sync_cob_id = 0x80
        self.sync_producer_enabled = False
        self.sync_period_us = 0

        # PDO マッピングパラメータ (1600h-1603h / 1A00h-1A03h)。既定値は EDS 実測。
        self.rpdo_mapping = [
            PdoMappingParams([MappingEntry(0x6040, 0, 16)]),
            PdoMappingParams([MappingEntry(0x6040, 0, 16), MappingEntry(0x6060, 0, 8)]),
            PdoMappingParams([MappingEntry(0x6040, 0, 16), MappingEntry(0x607A, 0, 32)]),
            PdoMappingParams([MappingEntry(0x6040, 0, 16), MappingEntry(0x60FF, 0, 32)]),
        ]
        self.tpdo_mapping = [
            PdoMappingParams([MappingEntry(0x6041, 0, 16)]),
            PdoMappingParams([MappingEntry(0x6041, 0, 16), MappingEntry(0x6061, 0, 8)]),
            PdoMappingParams([MappingEntry(0x6041, 0, 16), MappingEntry(0x6064, 0, 32)]),
            PdoMappingParams([MappingEntry(0x6041, 0, 16), MappingEntry(0x606C, 0, 32)]),
        ]

        # passthrough で書かれた値。インスタンスごとに独立。
        self.passthrough_values = {}

    # --- 外向きの窓口は以下の 4 つだけ ---

    def read_object(self, index, sub=0):
        return self.router.read(self, index, sub)

    def write_object(self, index, sub=0, value=0):
        self.router.write(self, index, sub, value)

    # validate_object の使い捨てコピーで deepcopy する対象。
    # writer が実際に変更しうる入れ子オブジェクト/コンテナのみを列挙する。
    # 新しい writer が別の入れ子オブジェクトを触るようになったら追記すること
    # (test_shadow_isolation_holds_for_every_registered_writer が検出する)。
    _SHADOW_DEEP_ATTRS = (
        "state_machine", "plant", "alarms", "passthrough_values",
        "rpdo_comm", "rpdo_mapping", "tpdo_comm", "tpdo_mapping",
        # 40D0h (Clear ETO) の writer が hwto を書き換えるため必須。
        # 漏らすと SDO 受信時の検証だけで実機の ETO が解除される。
        "hwto",
        # 60B8h の writer は probe 無効化時にラッチ値とカウンタを捨てる。
        "touch_probe_values", "touch_probe_counters",
        # 4033h の writer が起動待ちトリガと直近値を書き換える。
        "direct_data",
    )

    def _shadow(self):
        """validate_object 用の使い捨てコピーを作る。

        copy.deepcopy(self) は state_machine/plant/profile/units/operation/
        alarms など全ての入れ子オブジェクトを再帰的に複製するため、PDO の
        書込み頻度では重すぎる (P2 最終レビュー指摘)。writer が実際に
        変更するのは _SHADOW_DEEP_ATTRS のものだけで、profile・units・
        operation は writer から直接変更されない (target_velocity_rpm 等は
        DriverModel 自身のスカラー属性であり、shallow copy で自動的に
        独立になる)。そのため shallow copy + 上記だけを個別に deepcopy する。
        """
        shadow = copy.copy(self)
        for name in self._SHADOW_DEEP_ATTRS:
            setattr(shadow, name, copy.deepcopy(getattr(self, name)))
        return shadow

    def validate_object(self, index, sub=0, value=0):
        """index:sub に value を書き込めるかどうかだけを判定する（実体は書き換えない）。

        CAN 受信スレッド (od_bridge.on_write) が、キューに積む前に SDO の
        abort 応答を正しく返せるようにするための窓口。writer ハンドラの中
        には 40C0h のアラームリセットのように副作用を伴うものがあるため、
        「検証専用のロジックを別に書く」のではなく、writer ハンドラ自体を
        使い捨てコピー (_shadow()) 上で実際に走らせ、例外が出るかどうかで
        判定する。これなら検証ロジックと適用ロジックが二重に書かれてずれる
        ことがない。コピー側に生じた副作用はコピーごと捨てるため、呼び出し
        元の状態には一切影響しない。

        受け付けられない場合は ObjectAccessError（NotImplementedObjectError
        を含む）を投げる。
        """
        self.router.write(self._shadow(), index, sub, value)

    def stub_objects(self):
        """[(index, sub, 理由), ...] 未実装スタブオブジェクトの一覧。"""
        return self.router.stubs()

    def _context(self):
        return OperationContext(
            state_machine=self.state_machine,
            profile=self.profile,
            plant=self.plant,
            units=self.units,
            params=self,
        )

    def step(self, dt):
        self.sim_time += dt

        self._apply_hwto(dt)

        if self.alarms.is_active:
            self.state_machine.set_fault(True)
        self.state_machine.step(dt)

        self._sync_excited()

        if not self.state_machine.is_operation_enabled and self.state_machine.state in (
            State.FAULT, State.SWITCH_ON_DISABLED
        ):
            self.profile.reset(0.0)

        ctx = self._context()
        self.operation.step(dt, ctx)
        self.operation.apply_status_bits(ctx)

        # HP-5143E 6.2 (p35) Transition 12: quick-stop-active はクイック
        # ストップの減速完了 (指令・実速度ともに 0 付近) で switch-on-disabled
        # へ抜ける。抜けるかどうかと減速のしかたは 605Ah で決まる。
        if self.state_machine.state == State.QUICK_STOP_ACTIVE:
            action = resolve_quick_stop(self.quick_stop_option_code)
            if action.kind == IMMEDIATE:
                self.profile.reset(0.0)
                self.plant.velocity = 0.0
            stopped = (
                self.profile.command == 0.0
                and abs(self.actual_velocity_rpm) <= self.velocity_threshold_rpm
            )
            if stopped and not action.stay_in_state:
                self.state_machine.stop_completed()

        self._step_direct_data(dt)
        self._check_heartbeat_consumer()
        self._apply_travel_limits()

    @property
    def effective_deceleration_rpm_s(self):
        """今この瞬間に使う減速度。

        通常は 6084h。quick-stop-active の間だけ 605Ah の option code に
        従い、quick stop ramp なら 6085h を使う。運転モード側はこの値を
        参照する (モードごとに同じ分岐を書かないため)。
        """
        if self.state_machine.state != State.QUICK_STOP_ACTIVE:
            return self.profile_deceleration_rpm_s
        action = resolve_quick_stop(self.quick_stop_option_code)
        if action.kind == QUICK_STOP_RAMP:
            return self.quick_stop_deceleration_rpm_s
        return self.profile_deceleration_rpm_s

    # --- 停止動作の option code (605Ah-605Eh) と 6085h ---

    @router.reader(0x605A)
    def _read_quick_stop_option_code(self, sub):
        return self.quick_stop_option_code

    @router.writer(0x605A)
    def _write_quick_stop_option_code(self, sub, value):
        code = int(value)
        if code in (-3, -2):
            # 4735h Custom stopping rate / 4736h Custom stopping time は
            # 値を保持しているだけで単位が未確認 (P5 でアドレスコード表から
            # 確定させる)。挙動を推測で作らず、明示的に拒否する。
            raise ObjectAccessError(
                ABORT_VALUE_RANGE,
                "605Ah の {} (4735h/4736h によるカスタム停止) は未対応です".format(code))
        resolve_quick_stop(code)   # 範囲外はここで abort
        self.quick_stop_option_code = code

    @router.reader(0x605B)
    def _read_shutdown_option_code(self, sub):
        return self.shutdown_option_code

    @router.writer(0x605B, stub=_SHUTDOWN_OPTION_STUB_REASON)
    def _write_shutdown_option_code(self, sub, value):
        resolve_shutdown(value)
        self.shutdown_option_code = int(value)

    @router.reader(0x605C)
    def _read_disable_operation_option_code(self, sub):
        return self.disable_operation_option_code

    @router.writer(0x605C, stub=_DISABLE_OPERATION_OPTION_STUB_REASON)
    def _write_disable_operation_option_code(self, sub, value):
        resolve_disable_operation(value)
        self.disable_operation_option_code = int(value)

    @router.reader(0x605D)
    def _read_halt_option_code(self, sub):
        return self.halt_option_code

    @router.writer(0x605D)
    def _write_halt_option_code(self, sub, value):
        resolve_halt(value)   # 0 は仕様上 Reserved なので abort
        self.halt_option_code = int(value)

    @router.reader(0x605E)
    def _read_fault_reaction_option_code(self, sub):
        return self.fault_reaction_option_code

    @router.writer(0x605E, stub=_FAULT_REACTION_OPTION_STUB_REASON)
    def _write_fault_reaction_option_code(self, sub, value):
        resolve_fault_reaction(value)
        self.fault_reaction_option_code = int(value)

    @router.reader(0x6085)
    def _read_quick_stop_deceleration(self, sub):
        return int(self.quick_stop_deceleration_rpm_s)

    @router.writer(0x6085)
    def _write_quick_stop_deceleration(self, sub, value):
        if int(value) <= 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6085h は 1 以上")
        self.quick_stop_deceleration_rpm_s = float(value)

    # --- HWTO (動力遮断機能) ---

    def set_hwto_inputs(self, hwto1_on, hwto2_on):
        """CN4 の HWTO 入力状態を伝える。次の step() から効く。

        入力 ON = DC24V が来ている = 正常。OFF = 動力遮断が働く。
        配線 (何がこの入力を駆動するか) は omsim/sim/wiring.py が持つ。
        """
        self._hwto_inputs = (bool(hwto1_on), bool(hwto2_on))

    def _apply_hwto(self, dt):
        hwto1_on, hwto2_on = getattr(self, "_hwto_inputs", (True, True))
        self.hwto.set_inputs(hwto1_on, hwto2_on, dt)

        # HP-5143E 6.2 (p35) の遷移 7/9/10/12 は「HWTO signal input is active」でも
        # 起きる (= Disable Voltage 相当)。ステートマシンの voltage_enabled に
        # 落とせば、既存の遷移ロジックがそのまま使える。
        # 両方の入力が OFF になって ETO 状態に入った場合は、入力が戻っても
        # ETO-CLR (40D0h) で解除するまで無励磁のまま (HP-5141J p204)。
        self.state_machine.voltage_enabled = not (
            self.hwto.power_cut or self.hwto.eto_active)

        alarm = self.hwto.take_pending_alarm()
        if alarm == "circuit":
            self.alarms.raise_alarm(
                ALARM_HWTO_CIRCUIT, EMCY_HWTO_CIRCUIT, ERROR_REGISTER_HWTO)
        elif alarm == "detected":
            self.alarms.raise_alarm(
                ALARM_HWTO_DETECTED, EMCY_HWTO_DETECTED, ERROR_REGISTER_HWTO)

    @property
    def power_cut(self):
        """HWTO でトルクを出せない状態か。"""
        return self.hwto.power_cut

    @property
    def brake_engaged(self):
        """電磁ブレーキが保持されているか。

        HP-5141J p204: 動力遮断状態では「電磁ブレーキが保持されます」。
        励磁されていない間はブレーキが効いている、と同じ意味で扱う。
        """
        return self.power_cut or not self.plant.excited

    @router.reader(0x60FD)
    def _read_digital_inputs(self, sub):
        # HP-5143E 60FDh 実測: bit0 NLS / bit1 PLS / bit2 HS / bit3 HWTO /
        # bit16-31 R-OUT。リミットセンサとリモート出力は P4 以降のため 0。
        value = 0
        if self.limit_inputs["rv_ls"]:
            value |= 1 << 0   # NLS: Negative limit switch
        if self.limit_inputs["fw_ls"]:
            value |= 1 << 1   # PLS: Positive limit switch
        if self.limit_inputs["home"]:
            value |= 1 << 2   # HS: Home switch
        if self.hwto.hwtoin_mon:
            value |= 1 << 3
        return value

    @router.writer(0x40D0)
    def _write_clear_eto(self, sub, value):
        """40D0h Clear ETO。両方の HWTO 入力が ON に戻っていないと解除できない。"""
        if not int(value):
            return
        if not self.hwto.clear_eto():
            raise ObjectAccessError(
                ABORT_DEVICE_STATE,
                "40D0h: HWTO 入力が OFF のままなので ETO を解除できません")

    @router.reader(0x40D0)
    def _read_clear_eto(self, sub):
        # 実行トリガのため読み出しは常に 0 (EDS 既定値と同じ)。
        return 0

    def _sync_excited(self):
        """励磁状態 (plant.excited) をステートマシンの現在の状態から同期する。

        write_controlword() は state を同期的に遷移させるため、step() を
        待たずに励磁状態も同期する必要がある（次の step() 呼び出し前に励磁
        を観測するテストのため）。step() と _write_controlword() の両方
        から呼ばれる共通処理。
        """
        # quick-stop-active の間もドライバは励磁したままクイックストップの
        # 減速を実行する (HP-5143E 6.2 の遷移 11: 「The Quick Stop function is
        # executed」)。ここを励磁 OFF にすると、605Ah で指定した減速ランプが
        # 効かず惰走になってしまう。
        excited = (
            self.state_machine.is_operation_enabled
            or self.state_machine.state == State.QUICK_STOP_ACTIVE)
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
            # 3D 表示が軸の回転角を出すのに使う。JS 側に定数を二重に持たない。
            "increments_per_revolution": self.units.increments_per_shaft_rev,
            "power_cut": self.power_cut,
            "brake_engaged": self.brake_engaged,
            "hwto": {
                "hwto1_on": self.hwto.hwto1_on,
                "hwto2_on": self.hwto.hwto2_on,
                "eto_active": self.hwto.eto_active,
                "edm_mon": self.hwto.edm_mon,
                "hwtoin_mon": self.hwto.hwtoin_mon,
            },
            "alarm": self.alarms.active_alarm,
            "alarm_history": self.alarms.history,
        }

    # --- テストと Web からアラームを注入する口 ---

    def inject_alarm(self, alarm_code, emcy_code, error_register=0x21):
        self.alarms.raise_alarm(alarm_code, emcy_code, error_register)

    def clear_alarm_cause(self):
        """注入したアラームの原因が解消したことを外から通知する。

        実機では過負荷が収まる等に相当する。これを呼ばない限り 40C0h への
        アラームリセット書き込みは ObjectAccessError (ABORT_DEVICE_STATE) で
        失敗する（原因が続いている間は実機でもリセットできないため）。
        """
        self.alarms.set_cause_cleared(True)

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

    # --- SYNC (1005h / 1006h) ---

    _SYNC_PRODUCER_BIT = 1 << 30

    @router.reader(0x1005)
    def _read_sync_cob_id(self, sub):
        value = self.sync_cob_id & 0x7FF
        if self.sync_producer_enabled:
            value |= self._SYNC_PRODUCER_BIT
        return value

    @router.writer(0x1005)
    def _write_sync_cob_id(self, sub, value):
        raw = int(value) & 0xFFFFFFFF
        self.sync_cob_id = raw & 0x7FF
        self.sync_producer_enabled = bool(raw & self._SYNC_PRODUCER_BIT)

    @router.reader(0x1006)
    def _read_sync_period(self, sub):
        return self.sync_period_us

    @router.writer(0x1006)
    def _write_sync_period(self, sub, value):
        period = int(value)
        if not (0 <= period <= 1000000):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "1006h は 0-1,000,000 μs")
        self.sync_period_us = period

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

    _OPERATION_MODES = {
        MODE_PV: ProfileVelocityMode,
        MODE_PP: ProfilePositionMode,
        MODE_TQ: ProfileTorqueMode,
        MODE_HM: HomingMode,
    }

    @router.writer(0x6060)
    def _write_mode(self, sub, value):
        mode = int(value)
        factory = self._OPERATION_MODES.get(mode)
        if factory is None:
            raise NotImplementedObjectError(
                ABORT_DEVICE_STATE,
                "運転モード {} は未実装 (tq/hm は P4 の後続タスク, 6060h)".format(mode))
        if mode == self.mode:
            return
        self.mode = mode
        self.operation = factory()

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

    _TORQUE_LIMIT_STUB_REASON = (
        "P5: tq (トルク) モードではトルク制限として実際に効くが、pv / pp の"
        "速度・位置追従では MotorPlant がトルク制限を参照しないため効かない"
    )

    @router.reader(0x6072)
    def _read_max_torque(self, sub):
        return self.max_torque_permille

    @router.writer(0x6072)
    def _write_max_torque(self, sub, value):
        # EDS: LowLimit=0 HighLimit=10000 (千分率、1000 = 定格トルク)
        if not (0 <= int(value) <= 10000):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6072h は 0-10000")
        self.max_torque_permille = int(value)

    @router.reader(0x60FE, 1, stub="P5: HWTO/デジタル出力の意味付け未実装（値の保持のみ）")
    def _read_digital_outputs(self, sub):
        return self.digital_outputs

    @router.writer(0x60FE, 1, stub="P5: HWTO/デジタル出力の意味付け未実装（値の保持のみ）")
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
            # CiA301 では「データが無い」ことは 0 ではなく abort で表す。
            raise ObjectAccessError(
                ABORT_NO_DATA, "1003h:{:02X} はまだ記録がありません".format(sub))
        return history[sub - 1]

    # sub1〜10 は全て同じ「履歴の sub 番目を返す」処理のため、
    # 個別に @router.reader を書かずループでまとめて登録している。
    for _sub in range(1, 11):
        router.reader(0x1003, _sub)(_read_error_field)
    del _sub

    # --- メーカ固有 (pitakuru motor_control_node が実際に触れているもののみ) ---

    @router.reader(0x4032, stub=_TORQUE_LIMIT_STUB_REASON)
    def _read_direct_torque_limit(self, sub):
        return self.direct_torque_limit_permille

    @router.writer(0x4032, stub=_TORQUE_LIMIT_STUB_REASON)
    def _write_direct_torque_limit(self, sub, value):
        # EDS: LowLimit 記載無し。6072h と同じ千分率レンジとして扱う。
        # 6072h (Max torque) とは別オブジェクト（HP-5141J 第1章4節の通り
        # 独立したトルク制限ソース）のため、専用の変数に書く。
        if not (0 <= int(value) <= 10000):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "4032h は 0-10000")
        self.direct_torque_limit_permille = int(value)

    @router.reader(0x409B, stub="P6: 主電源電流のモデル未実装。常に 0 [mA] を返すだけ")
    def _read_main_power_current(self, sub):
        return 0

    def _limit_window(self):
        """(下限, 上限) を返す。無効なら None。

        HP-5143E 607Dh 実測: 「Corrected limit = limit - Home offset」で
        補正した値と実位置を比べる。
        """
        if not self.software_limits_active:
            return None
        return (self.software_min_position - self.home_offset,
                self.software_max_position - self.home_offset)

    def _blocked_direction(self):
        """止めるべき方向を返す (+1 / -1 / 0)。

        リミットセンサ (FW-LS / RV-LS) とソフトウェアリミットの両方を見る。
        センサに当たっていても反対方向へは動けること (HP-5141J の一般的な
        リミット動作) を守るため、方向つきで返す。
        """
        blocked = 0
        if self.limit_inputs["fw_ls"]:
            blocked = +1
        if self.limit_inputs["rv_ls"]:
            blocked = -1 if blocked == 0 else blocked
        window = self._limit_window()
        if window is not None:
            position = int(self.plant.position)
            if position >= window[1]:
                blocked = +1
            elif position <= window[0]:
                blocked = -1
        return blocked

    def _apply_travel_limits(self):
        """リミットに当たっていたら、その方向の動きだけを止める。"""
        blocked = self._blocked_direction()
        self.state_machine.internal_limit_active = blocked != 0
        if blocked == 0:
            return
        velocity = self.plant.velocity
        if (blocked > 0 and velocity > 0) or (blocked < 0 and velocity < 0):
            self.plant.velocity = 0.0
            self.profile.reset(0.0)
        window = self._limit_window()
        if window is None:
            return
        # ソフトウェアリミットは位置そのものが境界を越えないよう押し戻す。
        # 速度を 0 にするだけだと、毎周期わずかに動いては止められて、
        # 境界の外へじりじり進んでしまう (実測で 3000 周期に 57 increment)。
        position = int(self.plant.position)
        if position > window[1]:
            self.plant.preset_position(window[1])
        elif position < window[0]:
            self.plant.preset_position(window[0])

    # --- ダイレクトデータ運転 (402Ch-4034h) ---

    @property
    def direct_data_lifetime(self):
        return self.direct_data.lifetime

    def _start_direct_motion(self, kind):
        """反映トリガで起動する。励磁していなければ起動しない。"""
        if not self.plant.excited:
            return
        data = self.direct_data
        if kind == "immediate_stop":
            self.profile.reset(0.0)
            self.plant.velocity = 0.0
            self._direct_motion = None
            return
        # 反映トリガを書いた時点の運転データを取り込む。以後 402Eh-4031h を
        # 書き換えても、次のトリガまでは効かない (HP-5141J 4 章「データの
        # 書き換えと運転の開始を同時に行なう」)。
        snapshot = {
            "velocity": int(data.velocity),
            "acceleration": int(data.acceleration),
            "deceleration": int(data.deceleration),
        }
        if kind == "deceleration_stop":
            snapshot["kind"] = "stop"
            self._direct_motion = snapshot
            return
        if kind == "continuous_velocity":
            snapshot["kind"] = "velocity"
            self._direct_motion = snapshot
            return
        if kind == "absolute":
            target = int(data.position)
        elif kind == "relative_command":
            # 指令位置基準。指令位置は台形プロファイルの積分ではなく実位置に
            # 追従しているため、ここでは実位置を基準にする (検出位置基準との
            # 差は P6 で指令位置を別管理するときに入れる)。
            target = int(self.plant.position) + int(data.position)
        elif kind == "relative_detected":
            target = int(self.plant.position) + int(data.position)
        else:
            return
        snapshot["kind"] = "position"
        snapshot["target"] = target
        self._direct_motion = snapshot

    def _step_direct_data(self, dt):
        """ダイレクトデータ運転を 1 ステップ進める。

        CiA402 の運転モード (operation.step) は DriverModel.step の中で先に
        呼ばれている。ダイレクトデータ運転が動いている間は、その結果を
        上書きする形で位置/速度を作る。
        """
        pending = self.direct_data.take_pending_start()
        if pending is not None:
            self._start_direct_motion(pending)

        motion = self._direct_motion
        if motion is None:
            return
        if not self.plant.excited:
            self._direct_motion = None
            return

        self.profile.acceleration = self.units.rpm_to_internal(motion["acceleration"])
        self.profile.deceleration = self.units.rpm_to_internal(motion["deceleration"])

        if motion["kind"] == "velocity":
            self.profile.set_target(self.units.rpm_to_internal(motion["velocity"]))
        elif motion["kind"] == "stop":
            self.profile.set_target(0.0)
            if abs(self.plant.velocity) <= self.units.rpm_to_internal(
                    self.velocity_threshold_rpm):
                self._direct_motion = None
        else:
            remaining = motion["target"] - int(self.plant.position)
            threshold = self.units.rpm_to_internal(self.velocity_threshold_rpm)
            if abs(remaining) <= 2 and abs(self.plant.velocity) <= threshold:
                self.profile.set_target(0.0)
                self._direct_motion = None
            else:
                max_velocity = self.units.rpm_to_internal(motion["velocity"])
                deceleration = self.units.rpm_to_internal(motion["deceleration"])
                stoppable = (2.0 * deceleration * abs(remaining)) ** 0.5
                velocity = min(max_velocity, stoppable)
                self.profile.set_target(velocity if remaining > 0 else -velocity)

        self.profile.step(dt)
        self.plant.step(dt, self.profile.command)

    @router.reader(0x402C)
    def _read_direct_data_number(self, sub):
        return self.direct_data.data_number

    @router.writer(0x402C)
    def _write_direct_data_number(self, sub, value):
        self.direct_data.data_number = int(value)

    @router.reader(0x402D)
    def _read_direct_operation_type(self, sub):
        return self.direct_data.operation_type

    @router.writer(0x402D)
    def _write_direct_operation_type(self, sub, value):
        resolve_operation_type(value)   # 未対応/範囲外はここで abort
        self.direct_data.operation_type = int(value)

    @router.reader(0x402E)
    def _read_direct_position(self, sub):
        return _clamp_int32(self.direct_data.position)

    @router.writer(0x402E)
    def _write_direct_position(self, sub, value):
        self.direct_data.position = _clamp_int32(value)

    @router.reader(0x402F)
    def _read_direct_velocity(self, sub):
        return int(self.direct_data.velocity)

    @router.writer(0x402F)
    def _write_direct_velocity(self, sub, value):
        self.direct_data.velocity = int(value)

    @router.reader(0x4030)
    def _read_direct_acceleration(self, sub):
        return int(self.direct_data.acceleration)

    @router.writer(0x4030)
    def _write_direct_acceleration(self, sub, value):
        if int(value) <= 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "4030h は 1 以上")
        self.direct_data.acceleration = int(value)

    @router.reader(0x4031)
    def _read_direct_deceleration(self, sub):
        return int(self.direct_data.deceleration)

    @router.writer(0x4031)
    def _write_direct_deceleration(self, sub, value):
        if int(value) <= 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "4031h は 1 以上")
        self.direct_data.deceleration = int(value)

    @router.reader(0x4033)
    def _read_direct_trigger(self, sub):
        return self.direct_data.encoded_trigger()

    @router.writer(0x4033)
    def _write_direct_trigger(self, sub, value):
        self.direct_data.write_trigger(value)

    @router.reader(0x4034)
    def _read_direct_forwarding_destination(self, sub):
        return self.direct_data.forwarding_destination

    @router.writer(0x4034)
    def _write_direct_forwarding_destination(self, sub, value):
        if int(value) not in (0, 1):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "4034h は 0 か 1")
        self.direct_data.forwarding_destination = int(value)

    # --- touch probe (60B8h-60BDh / 60D5h-60D8h) ---

    _PROBE_BITS = {
        # probe: (有効化, 連続, トリガ源 ZSG, 正エッジ, 負エッジ, status 基準ビット)
        1: (0, 1, 2, 4, 5, 0),
        2: (8, 9, 10, 12, 13, 8),
    }

    def _probe_flag(self, probe, which):
        bits = self._PROBE_BITS[probe]
        index = {"enable": 0, "continuous": 1, "zsg": 2,
                 "positive": 3, "negative": 4}[which]
        return bool(self.touch_probe_function & (1 << bits[index]))

    def trigger_touch_probe(self, probe, edge):
        """probe 入力 (USR-LAT-IN0/1) のエッジを伝える。

        CN4 の実際の入力割付は P5。ここは「エッジが来た」という事実だけを
        受ける内部 API。
        """
        if probe not in self._PROBE_BITS:
            raise ValueError("touch probe は 1 か 2 です: {}".format(probe))
        if edge not in ("positive", "negative"):
            raise ValueError("edge は positive か negative です: {}".format(edge))
        if not self._probe_flag(probe, "enable"):
            return
        if not self._probe_flag(probe, edge):
            return
        stored = self.touch_probe_values[probe][edge]
        if stored is not None and not self._probe_flag(probe, "continuous"):
            # 単発モードは最初のイベントだけを保持する
            return
        self.touch_probe_values[probe][edge] = int(self.plant.position)
        self.touch_probe_counters[probe][edge] += 1

    @router.reader(0x60B8)
    def _read_touch_probe_function(self, sub):
        return self.touch_probe_function

    @router.writer(0x60B8)
    def _write_touch_probe_function(self, sub, value):
        raw = int(value) & 0xFFFF
        for probe, bits in self._PROBE_BITS.items():
            if raw & (1 << bits[2]):
                raise NotImplementedObjectError(
                    ABORT_VALUE_RANGE,
                    "60B8h: probe{} の ZSG-N トリガ源は未実装 "
                    "(index pulse のモデルが無い)".format(probe))
        was_enabled = dict(
            (probe, self._probe_flag(probe, "enable")) for probe in self._PROBE_BITS)
        self.touch_probe_function = raw
        for probe in self._PROBE_BITS:
            if was_enabled[probe] and not self._probe_flag(probe, "enable"):
                # 無効化したら保持値とカウンタを捨てる (status も落ちる)
                self.touch_probe_values[probe] = {"positive": None, "negative": None}
                self.touch_probe_counters[probe] = {"positive": 0, "negative": 0}

    @router.reader(0x60B9)
    def _read_touch_probe_status(self, sub):
        value = 0
        for probe, bits in self._PROBE_BITS.items():
            base = bits[5]
            if self._probe_flag(probe, "enable"):
                value |= 1 << base
            if self.touch_probe_values[probe]["positive"] is not None:
                value |= 1 << (base + 1)
            if self.touch_probe_values[probe]["negative"] is not None:
                value |= 1 << (base + 2)
        return value

    def _probe_value(self, probe, edge):
        stored = self.touch_probe_values[probe][edge]
        return _clamp_int32(stored if stored is not None else 0)

    @router.reader(0x60BA)
    def _read_probe1_positive(self, sub):
        return self._probe_value(1, "positive")

    @router.reader(0x60BB)
    def _read_probe1_negative(self, sub):
        return self._probe_value(1, "negative")

    @router.reader(0x60BC)
    def _read_probe2_positive(self, sub):
        return self._probe_value(2, "positive")

    @router.reader(0x60BD)
    def _read_probe2_negative(self, sub):
        return self._probe_value(2, "negative")

    @router.reader(0x60D5)
    def _read_probe1_positive_counter(self, sub):
        return self.touch_probe_counters[1]["positive"]

    @router.reader(0x60D6)
    def _read_probe1_negative_counter(self, sub):
        return self.touch_probe_counters[1]["negative"]

    @router.reader(0x60D7)
    def _read_probe2_positive_counter(self, sub):
        return self.touch_probe_counters[2]["positive"]

    @router.reader(0x60D8)
    def _read_probe2_negative_counter(self, sub):
        return self.touch_probe_counters[2]["negative"]

    # --- hm (Homing) と原点まわり ---

    def set_limit_inputs(self, fw_ls=None, rv_ls=None, home=None):
        """CN4 のリミット / HOME センサ入力を伝える (実配線は P5)。"""
        for name, value in (("fw_ls", fw_ls), ("rv_ls", rv_ls), ("home", home)):
            if value is not None:
                self.limit_inputs[name] = bool(value)

    def on_homing_completed(self):
        """HomingMode から呼ばれる。原点復帰完了でソフトリミットが有効になる。"""
        self.homing_completed = True

    @property
    def homing_backward_steps(self):
        """4169h (HOME) 2 センサ原点復帰の戻りステップ数。未設定なら 0。"""
        value = self.passthrough_values.get((0x4169, 0))
        return int(value) if value is not None else 0

    @property
    def software_limits_active(self):
        """607Dh が効いているか。

        HP-5143E 607Dh 実測: 有効になるのは原点復帰完了後。Min >= Max、または
        Min/Max がともに 0 のときは無効。
        """
        if not self.homing_completed:
            return False
        if self.software_min_position == 0 and self.software_max_position == 0:
            return False
        return self.software_min_position < self.software_max_position

    _UNSUPPORTED_HOMING_METHODS = (1, 2, 8, 12, -1)

    @router.reader(0x6098)
    def _read_homing_method(self, sub):
        return self.homing_method

    @router.writer(0x6098)
    def _write_homing_method(self, sub, value):
        method = int(value)
        if not (-1 <= method <= 37):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6098h は -1〜37")
        if method in self._UNSUPPORTED_HOMING_METHODS:
            raise NotImplementedObjectError(
                ABORT_VALUE_RANGE,
                "6098h の方式 {} は未実装 (index pulse (ZSG-N) / メーカ固有)".format(method))
        if method not in HomingMode.SEARCH and method not in HomingMode.CURRENT_POSITION_METHODS:
            raise NotImplementedObjectError(
                ABORT_VALUE_RANGE, "6098h の方式 {} は未実装".format(method))
        self.homing_method = method

    @router.reader(0x6099, 0)
    def _read_homing_speeds_count(self, sub):
        return 2

    @router.reader(0x6099, 1)
    def _read_homing_speed_switch(self, sub):
        return int(self.homing_speed_switch_rpm)

    @router.writer(0x6099, 1)
    def _write_homing_speed_switch(self, sub, value):
        if not (1 <= int(value) <= 4000000):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6099h:01 は 1〜4,000,000")
        self.homing_speed_switch_rpm = int(value)

    @router.reader(0x6099, 2)
    def _read_homing_speed_zero(self, sub):
        return int(self.homing_speed_zero_rpm)

    @router.writer(0x6099, 2)
    def _write_homing_speed_zero(self, sub, value):
        if not (1 <= int(value) <= 4000000):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6099h:02 は 1〜4,000,000")
        self.homing_speed_zero_rpm = int(value)

    @router.reader(0x609A)
    def _read_homing_acceleration(self, sub):
        return int(self.homing_acceleration_rpm_s)

    @router.writer(0x609A)
    def _write_homing_acceleration(self, sub, value):
        if int(value) <= 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "609Ah は 1 以上")
        self.homing_acceleration_rpm_s = int(value)

    @router.reader(0x607C)
    def _read_home_offset(self, sub):
        return _clamp_int32(self.home_offset)

    @router.writer(0x607C)
    def _write_home_offset(self, sub, value):
        self.home_offset = _clamp_int32(value)

    @router.reader(0x607D, 0)
    def _read_software_limit_count(self, sub):
        return 2

    @router.reader(0x607D, 1)
    def _read_software_min_position(self, sub):
        return _clamp_int32(self.software_min_position)

    @router.writer(0x607D, 1)
    def _write_software_min_position(self, sub, value):
        self.software_min_position = _clamp_int32(value)

    @router.reader(0x607D, 2)
    def _read_software_max_position(self, sub):
        return _clamp_int32(self.software_max_position)

    @router.writer(0x607D, 2)
    def _write_software_max_position(self, sub, value):
        self.software_max_position = _clamp_int32(value)

    @router.reader(0x6071)
    def _read_target_torque(self, sub):
        return self.target_torque

    @router.writer(0x6071)
    def _write_target_torque(self, sub, value):
        # EDS/HP-5143E: -1000..1000 (0.1% 単位)
        if not (-1000 <= int(value) <= 1000):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6071h は -1000〜1000")
        self.target_torque = int(value)

    @router.reader(0x6074)
    def _read_torque_demand(self, sub):
        demand = getattr(self.operation, "torque_demand", None)
        # tq 以外のモードでは要求トルクという概念が無いので実トルクを返す。
        if demand is None:
            return _clamp_int32(round(self.plant.torque_permille))
        return demand

    @router.reader(0x6087)
    def _read_torque_slope(self, sub):
        return self.torque_slope

    @router.writer(0x6087)
    def _write_torque_slope(self, sub, value):
        if not (0 <= int(value) <= 1000000):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6087h は 0〜1,000,000")
        self.torque_slope = int(value)

    @router.reader(0x607A)
    def _read_target_position(self, sub):
        return _clamp_int32(self.target_position)

    @router.writer(0x607A)
    def _write_target_position(self, sub, value):
        self.target_position = _clamp_int32(value)

    @router.reader(0x6082)
    def _read_end_velocity(self, sub):
        return int(self.end_velocity)

    @router.writer(0x6082)
    def _write_end_velocity(self, sub, value):
        # 6082h は「加速終了時の速度」ではなく位置決め終了時の速度。0 以外は
        # 未対応。黙って 0 として動かすと「設定したのに効かない」嘘になるため
        # 明示的に拒否する。
        if int(value) != 0:
            raise ObjectAccessError(
                ABORT_VALUE_RANGE, "6082h は 0 以外未対応 (位置決めは必ず停止で終わる)")
        self.end_velocity = 0

    _POSITIONING_OPTION_SUPPORTED_MASK = 0x00C3   # bit0-1 (RO) と bit6-7 (RADO)

    @router.reader(0x60F2)
    def _read_positioning_option_code(self, sub):
        return self.positioning_option_code

    @router.writer(0x60F2)
    def _write_positioning_option_code(self, sub, value):
        raw = int(value) & 0xFFFF
        # HP-5143E 7.3.6 実測: Change immediately option (bit2-3) /
        # Request-response option (bit4-5) / IP option (bit8-11) は
        # 「Not supported」。立てられたら abort する。
        if raw & ~self._POSITIONING_OPTION_SUPPORTED_MASK:
            raise ObjectAccessError(
                ABORT_VALUE_RANGE,
                "60F2h の {:04X}h には未サポートのオプションが含まれています".format(raw))
        if raw:
            raise NotImplementedObjectError(
                ABORT_VALUE_RANGE,
                "60F2h: Relative option / Rotary axis direction option は"
                "値 0 (既定) のみ実装 (P4 の後続タスク)")
        self.positioning_option_code = raw

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
        raw = int(value) & 0xFFFFFFFF
        self.consumer_heartbeat_config = raw
        self.heartbeat_consumer_node_id = (raw >> 16) & 0xFF
        self.heartbeat_consumer_time_ms = raw & 0xFFFF
        enabled = bool(
            self.heartbeat_consumer_node_id and self.heartbeat_consumer_time_ms)
        self._heartbeat_consumer_reference_time = self.sim_time if enabled else None

    # --- node guarding (100Ch/100Dh) と Heartbeat consumer の判定 ---

    def _check_heartbeat_consumer(self):
        if not self.heartbeat_consumer_node_id or not self.heartbeat_consumer_time_ms:
            return
        if self._heartbeat_consumer_reference_time is None:
            return
        elapsed_ms = (self.sim_time - self._heartbeat_consumer_reference_time) * 1000.0
        if elapsed_ms > self.heartbeat_consumer_time_ms:
            self.alarms.raise_alarm(
                alarm_code=0, emcy_code=EMCY_HEARTBEAT_ERROR, error_register=0x11)

    def on_heartbeat_received(self, node_id, sim_time):
        """監視対象ノードからの Heartbeat/boot-up 受信を伝える。

        node/realtime_bridge.py から呼ばれる (driver 層に can 依存を
        持ち込まないための窓口)。
        """
        if node_id != self.heartbeat_consumer_node_id:
            return
        self._heartbeat_consumer_reference_time = sim_time
        if self.alarms.is_active and self.alarms.error_code == EMCY_HEARTBEAT_ERROR:
            self.alarms.set_cause_cleared(True)
            self.alarms.reset()

    @router.reader(0x100C)
    def _read_guard_time(self, sub):
        return self.guard_time_ms

    @router.writer(0x100C)
    def _write_guard_time(self, sub, value):
        time_ms = int(value)
        if not (0 <= time_ms <= 65535):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "100Ch は 0-65535")
        self.guard_time_ms = time_ms

    @router.reader(0x100D)
    def _read_life_time_factor(self, sub):
        return self.life_time_factor

    @router.writer(0x100D)
    def _write_life_time_factor(self, sub, value):
        factor = int(value)
        if not (0 <= factor <= 255):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "100Dh は 0-255")
        self.life_time_factor = factor

    @router.reader(0x1017)
    def _read_producer_heartbeat_time(self, sub):
        # Heartbeat producer は canopen.LocalNode.__init__() が
        # self.add_write_callback(self.nmt.on_write) を無条件に登録して
        # おり、NmtSlave が 1017h への書き込みをフックして
        # network.send_periodic() で周期送信を開始するため、実装済み。
        # ただし DriverModel 側には配線されていない（ドライバの状態には
        # 影響しない）。値の保持と CANopen への受け渡しのみ行う。
        # controller の実測確認: 1017h=200 で CAN ID 701 に 200ms 周期
        # でハートビートフレーム (701 [1] 7F) が出現。
        return self.producer_heartbeat_config

    @router.writer(0x1017)
    def _write_producer_heartbeat_time(self, sub, value):
        # 上記の通り canopen.NmtSlave がフックして周期送信を管理する。
        self.producer_heartbeat_config = int(value) & 0xFFFF

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
            if not self.alarms.reset():
                raise ObjectAccessError(
                    ABORT_DEVICE_STATE,
                    "40C0h: アラームの原因が解消していないため解除できません"
                    "（clear_alarm_cause() が呼ばれていない）")
            self.state_machine.set_fault(False)

    router.mark_stub(
        0x0000, 0x81,
        "P3: NMT reset (0x81) は canopen.NmtSlave が通信状態のみ処理し、"
        "DriverModel の状態（アラーム/ステートマシン/パラメータ等）には"
        "何も伝わらない。配線 (reset 受信時に DriverModel を初期化し直す) "
        "は P3 で実施予定"
    )

    # --- PDO 通信パラメータ (1400h-1403h / 1800h-1803h) ---

    def _write_pdo_comm_cob_id(self, params_list, slot, value, allow_rtr_bit):
        raw = int(value) & 0xFFFFFFFF
        decoded = PdoCommParams.decode_cob_id_sub1(raw)
        if not allow_rtr_bit and not decoded["rtr_allowed"]:
            # RPDO の COB-ID には RTR ビットの意味が無い (常に ZERO 領域)。
            # 立てて書かれても無視して常に許可扱いにする (実害が無いため
            # abort まではしない)。
            decoded["rtr_allowed"] = True
        params_list[slot].cob_id = decoded["cob_id"]
        params_list[slot].rtr_allowed = decoded["rtr_allowed"]
        params_list[slot].valid = decoded["valid"]

    def _write_transmission_type(self, params_list, slot, value, allowed_check):
        value = int(value)
        if not allowed_check(value):
            raise ObjectAccessError(
                0x06090030, "{:02X}h は未対応の transmission type です".format(value))
        params_list[slot].transmission_type = value

    # RPDO 通信パラメータ (1400h-1403h)
    for _slot, _index in enumerate((0x1400, 0x1401, 0x1402, 0x1403)):
        def _make_rpdo_comm_handlers(slot=_slot, index=_index):
            # ループ変数はキーワード引数の既定値で捕捉する。自由変数のまま
            # 参照すると del 後に全スロットが最後の値を見る (Python の罠)。
            def read_highest(self, sub):
                return 2

            def read_cob_id(self, sub):
                return self.rpdo_comm[slot].encode_cob_id_sub1()

            def write_cob_id(self, sub, value):
                self._write_pdo_comm_cob_id(
                    self.rpdo_comm, slot, value, allow_rtr_bit=False)

            def read_tt(self, sub):
                return self.rpdo_comm[slot].transmission_type

            def write_tt(self, sub, value):
                self._write_transmission_type(
                    self.rpdo_comm, slot, value,
                    lambda v: v in RPDO_TRANSMISSION_TYPES)

            return read_highest, read_cob_id, write_cob_id, read_tt, write_tt

        _read_highest, _read_cob_id, _write_cob_id, _read_tt, _write_tt = (
            _make_rpdo_comm_handlers())
        router.reader(_index, 0)(_read_highest)
        router.reader(_index, 1)(_read_cob_id)
        router.writer(_index, 1)(_write_cob_id)
        router.reader(_index, 2)(_read_tt)
        router.writer(_index, 2)(_write_tt)
    del _slot, _index

    # TPDO 通信パラメータ (1800h-1803h)
    for _slot, _index in enumerate((0x1800, 0x1801, 0x1802, 0x1803)):
        def _make_tpdo_comm_handlers(slot=_slot, index=_index):
            def read_highest(self, sub):
                return 5

            def read_cob_id(self, sub):
                return self.tpdo_comm[slot].encode_cob_id_sub1()

            def write_cob_id(self, sub, value):
                self._write_pdo_comm_cob_id(
                    self.tpdo_comm, slot, value, allow_rtr_bit=True)

            def read_tt(self, sub):
                return self.tpdo_comm[slot].transmission_type

            def write_tt(self, sub, value):
                self._write_transmission_type(
                    self.tpdo_comm, slot, value, is_supported_tpdo_transmission_type)

            def read_inhibit(self, sub):
                return self.tpdo_comm[slot].inhibit_time_100us

            def write_inhibit(self, sub, value):
                self.tpdo_comm[slot].inhibit_time_100us = int(value) & 0xFFFF

            def read_event(self, sub):
                return self.tpdo_comm[slot].event_timer_ms

            def write_event(self, sub, value):
                self.tpdo_comm[slot].event_timer_ms = int(value) & 0xFFFF

            return (read_highest, read_cob_id, write_cob_id, read_tt, write_tt,
                    read_inhibit, write_inhibit, read_event, write_event)

        (_read_highest, _read_cob_id, _write_cob_id, _read_tt, _write_tt,
         _read_inhibit, _write_inhibit, _read_event, _write_event) = (
            _make_tpdo_comm_handlers())
        router.reader(_index, 0)(_read_highest)
        router.reader(_index, 1)(_read_cob_id)
        router.writer(_index, 1)(_write_cob_id)
        router.reader(_index, 2)(_read_tt)
        router.writer(_index, 2)(_write_tt)
        router.reader(_index, 3)(_read_inhibit)
        router.writer(_index, 3)(_write_inhibit)
        router.reader(_index, 5)(_read_event)
        router.writer(_index, 5)(_write_event)
    del _slot, _index

    # --- PDO マッピングパラメータ (1600h-1603h / 1A00h-1A03h) ---

    def _mapping_disabled_guard(self, comm_params):
        if comm_params.valid:
            raise ObjectAccessError(
                ABORT_DEVICE_STATE,
                "対応する PDO が有効 (bit31=0) な間はマッピングを変更できません")

    def _write_mapping_count(self, mapping_params, comm_params, value):
        self._mapping_disabled_guard(comm_params)
        count = int(value)
        if not (0 <= count <= PdoMappingParams.MAX_ENTRIES):
            raise ObjectAccessError(ABORT_VALUE_RANGE, "マッピング数は 0-4")
        if count == 0:
            mapping_params.entries = []
            return
        if count > len(mapping_params.entries):
            raise ObjectAccessError(
                ABORT_DEVICE_STATE,
                "sub{} まで書き込んでから sub0 を {} にしてください".format(count, count))
        mapping_params.entries = mapping_params.entries[:count]

    def _write_mapping_entry(self, mapping_params, comm_params, sub, value):
        self._mapping_disabled_guard(comm_params)
        entry = unpack_mapping_entry(int(value) & 0xFFFFFFFF)
        if entry.length_bits % 8 != 0:
            raise ObjectAccessError(
                ABORT_VALUE_RANGE,
                "{}bit はバイト境界に揃っていません (このフェーズはバイト単位のみ対応)"
                .format(entry.length_bits))
        while len(mapping_params.entries) < sub:
            mapping_params.entries.append(MappingEntry(0, 0, 0))
        mapping_params.entries[sub - 1] = entry

    # RPDO マッピングパラメータ (1600h-1603h)
    for _slot, _index in enumerate((0x1600, 0x1601, 0x1602, 0x1603)):
        def _make_rpdo_mapping_handlers(slot=_slot):
            def read_count(self, sub):
                return self.rpdo_mapping[slot].count

            def write_count(self, sub, value):
                self._write_mapping_count(
                    self.rpdo_mapping[slot], self.rpdo_comm[slot], value)

            def read_entry(self, sub):
                entries = self.rpdo_mapping[slot].entries
                if sub > len(entries):
                    return 0
                e = entries[sub - 1]
                return pack_mapping_entry(e.index, e.sub, e.length_bits)

            def write_entry(self, sub, value):
                self._write_mapping_entry(
                    self.rpdo_mapping[slot], self.rpdo_comm[slot], sub, value)

            return read_count, write_count, read_entry, write_entry

        _read_count, _write_count, _read_entry, _write_entry = (
            _make_rpdo_mapping_handlers())
        router.reader(_index, 0)(_read_count)
        router.writer(_index, 0)(_write_count)
        for _sub in (1, 2, 3, 4):
            router.reader(_index, _sub)(_read_entry)
            router.writer(_index, _sub)(_write_entry)
    del _slot, _index, _sub

    # TPDO マッピングパラメータ (1A00h-1A03h)
    for _slot, _index in enumerate((0x1A00, 0x1A01, 0x1A02, 0x1A03)):
        def _make_tpdo_mapping_handlers(slot=_slot):
            def read_count(self, sub):
                return self.tpdo_mapping[slot].count

            def write_count(self, sub, value):
                self._write_mapping_count(
                    self.tpdo_mapping[slot], self.tpdo_comm[slot], value)

            def read_entry(self, sub):
                entries = self.tpdo_mapping[slot].entries
                if sub > len(entries):
                    return 0
                e = entries[sub - 1]
                return pack_mapping_entry(e.index, e.sub, e.length_bits)

            def write_entry(self, sub, value):
                self._write_mapping_entry(
                    self.tpdo_mapping[slot], self.tpdo_comm[slot], sub, value)

            return read_count, write_count, read_entry, write_entry

        _read_count, _write_count, _read_entry, _write_entry = (
            _make_tpdo_mapping_handlers())
        router.reader(_index, 0)(_read_count)
        router.writer(_index, 0)(_write_count)
        for _sub in (1, 2, 3, 4):
            router.reader(_index, _sub)(_read_entry)
            router.writer(_index, _sub)(_write_entry)
    del _slot, _index, _sub

    # --- .mxex に保存される純パラメータ群 ---
    # 値を保持して読み返せるが、挙動には効かない。実装フェーズは各行のとおり。
    # netid == index - 0x4000 で mxex と対応する (設計書 2.3)。
    _PASSTHROUGH_PARAMETERS = (
        (0x4148, "P5: 絶対座標未設定時の絶対位置決め許可。値の保持のみ"),
        (0x414B, "P5: ATL 機能モード設定。値の保持のみ"),
        (0x415F, "P5: JOG/HOME トルク制限値。値の保持のみ"),
        (0x4160, "P5: (HOME) 原点復帰モード。値の保持のみ"),
        (0x4163, "P5: (HOME) 起動速度。値の保持のみ"),
        (0x4169, "P5: (HOME) 2 センサ原点復帰の戻りステップ数。値の保持のみ"),
        (0x4186, "P6: アラーム発生時の停止タイムアウト。値の保持のみ"),
        (0x41A4, "P5: モーター回転方向。値の保持のみ"),
        (0x41CA, "P5: WRAP 設定。値の保持のみ"),
        (0x4735, "P4: カスタム停止レート。値の保持のみ"),
        (0x4736, "P4: カスタム停止時間。値の保持のみ"),
    )

    for _index, _reason in _PASSTHROUGH_PARAMETERS:
        router.passthrough(_index, 0, _reason)
    del _index, _reason
