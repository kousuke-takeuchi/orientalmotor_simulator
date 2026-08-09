"""BLVD-KRD ドライバの挙動モデル。can / canopen を import しないこと。

参照: HP-5143E 7.2 Profile Velocity Mode (p37)、HP-5141J 第1章 (p12-48)
"""
import copy

from omsim.driver.alarm_model import EMCY_HEARTBEAT_ERROR, AlarmModel
from omsim.driver.errors import (
    ABORT_DEVICE_STATE,
    ABORT_NO_DATA,
    ABORT_VALUE_RANGE,
    NotImplementedObjectError,
    ObjectAccessError,
)
from omsim.driver.motor_plant import MotorPlant
from omsim.driver.objects import ObjectRouter
from omsim.driver.operation import OperationContext, ProfileVelocityMode
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
        self.consumer_heartbeat_config = 0
        self.producer_heartbeat_config = 0
        # 605Ah Quick stop option code: 未実装 (P5)。値は保持するのみで、
        # 挙動には反映しない（常に既定の「減速完了で switch-on-disabled」）。
        self.quick_stop_option_code = 2

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
        # へ自動的に抜ける。605Ah Quick stop option code は未実装 (P5) の
        # ため、常にこの既定動作のみを行う。
        if self.state_machine.state == State.QUICK_STOP_ACTIVE:
            stopped = (
                self.profile.command == 0.0
                and abs(self.actual_velocity_rpm) <= self.velocity_threshold_rpm
            )
            if stopped:
                self.state_machine.stop_completed()

        self._check_heartbeat_consumer()

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
            # 3D 表示が軸の回転角を出すのに使う。JS 側に定数を二重に持たない。
            "increments_per_revolution": self.units.increments_per_shaft_rev,
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

    @router.writer(0x6060)
    def _write_mode(self, sub, value):
        mode = int(value)
        if mode != MODE_PV:
            raise NotImplementedObjectError(
                ABORT_DEVICE_STATE,
                "運転モード {} は未実装 (P4 で実装予定, 6060h)".format(mode))
        self.mode = mode
        self.operation = ProfileVelocityMode()

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
        "P4/P5: 値は保持・読み返しできるが MotorPlant がトルク制限を"
        "一切参照しないため、運転(速度追従)には効かない"
    )

    @router.reader(0x6072, stub=_TORQUE_LIMIT_STUB_REASON)
    def _read_max_torque(self, sub):
        return self.max_torque_permille

    @router.writer(0x6072, stub=_TORQUE_LIMIT_STUB_REASON)
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

    @router.reader(0x6081, stub="P4: pp (プロファイル位置) モード未実装。値の保持のみ")
    def _read_profile_velocity(self, sub):
        return int(self.profile_velocity_rpm)

    @router.writer(0x6081, stub="P4: pp (プロファイル位置) モード未実装。値の保持のみ")
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

    _QUICK_STOP_OPTION_STUB_REASON = (
        "P5: Quick stop option code 未実装。605Ah の値によらず、常に通常の"
        "減速度 (6084h) でクイックストップし、停止完了で switch-on-disabled "
        "へ抜ける既定動作のみを行う（6085h Quick stop deceleration も未実装）"
    )

    @router.reader(0x605A, stub=_QUICK_STOP_OPTION_STUB_REASON)
    def _read_quick_stop_option_code(self, sub):
        return self.quick_stop_option_code

    @router.writer(0x605A, stub=_QUICK_STOP_OPTION_STUB_REASON)
    def _write_quick_stop_option_code(self, sub, value):
        self.quick_stop_option_code = int(value)

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
