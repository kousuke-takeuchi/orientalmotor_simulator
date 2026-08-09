"""運転モード。CiA402 の Modes of operation (6060h) ごとの振る舞いを持つ。

DriverModel は「どのモードか」を選ぶだけにして、モードごとの制御則と
Statusword のモード固有ビット (bit10/12/13) の意味づけをここに閉じ込める。
P4 で pp / hm / tq を足すときは、このクラスを増やすだけで済む形にしてある。
モード固有ビット (bit10/12/13) の意味はモードごとに違う (pv の bit12 は
「速度が 0」、pp では Set point acknowledge、hm では Homing attained)。

参照: HP-5143E 7 章 (Operation mode)
"""
import collections

OperationContext = collections.namedtuple(
    "OperationContext", ["state_machine", "profile", "plant", "units", "params"]
)


class OperationMode(object):
    """運転モードの基底。"""

    @property
    def mode_code(self):
        """6060h / 6061h に載るモード番号。"""
        raise NotImplementedError("mode_code はサブクラスが実装する")

    def step(self, dt, ctx):
        """1 ステップぶん、指令を生成してプラントを進める。"""
        raise NotImplementedError("step はサブクラスが実装する")

    def apply_status_bits(self, ctx):
        """Statusword のモード固有ビットを更新する。"""
        raise NotImplementedError("apply_status_bits はサブクラスが実装する")


class ProfileVelocityMode(OperationMode):
    """Profile Velocity Mode (pv)。HP-5143E 7.2 (p37)。"""

    MODE_CODE = 3

    @property
    def mode_code(self):
        return self.MODE_CODE

    def step(self, dt, ctx):
        params = ctx.params
        ctx.profile.acceleration = ctx.units.rpm_to_internal(
            params.profile_acceleration_rpm_s)
        # 減速度は「今この瞬間に使うべき値」をモデルに聞く。quick-stop-active
        # では 605Ah の option code に従って 6085h に切り替わる。
        ctx.profile.deceleration = ctx.units.rpm_to_internal(
            params.effective_deceleration_rpm_s)

        # 速度指令に追従するのは operation-enabled のときだけ。
        # quick-stop-active では励磁したまま 0 へ減速する (励磁の有無ではなく
        # 状態で判断しないと、クイックストップ中も指令を追い続けてしまう)。
        if ctx.state_machine.is_operation_enabled:
            ctx.profile.set_target(
                ctx.units.rpm_to_internal(params.effective_target_velocity_rpm))
        else:
            ctx.profile.set_target(0.0)

        ctx.profile.step(dt)
        ctx.plant.step(dt, ctx.profile.command)

    def apply_status_bits(self, ctx):
        params = ctx.params
        actual_rpm = ctx.units.internal_to_rpm(ctx.plant.velocity)
        command_rpm = ctx.units.internal_to_rpm(ctx.profile.command)

        ctx.state_machine.target_reached = (
            ctx.plant.excited
            and ctx.profile.at_target
            and abs(actual_rpm - command_rpm) <= params.velocity_window_rpm
        )
        # HP-5143E 7.2.4 (p39): pv の bit12 (SPD) は「速度が 0 かどうか」。
        ctx.state_machine.operation_mode_specific_12 = (
            abs(actual_rpm) <= params.velocity_threshold_rpm
        )


class ProfilePositionMode(OperationMode):
    """Profile Position Mode (pp)。HP-5143E 7.3 (p42-46)。

    Controlword: bit4 NSP (New set point) / bit5 IMM (Change set immediately) /
                 bit6 REL (Abs/rel) / bit8 HALT
    Statusword : bit10 TR (Target reached) / bit12 SPA (Set point acknowledge)

    位置決めは「残距離から出せる最大速度」を毎周期求め、それを速度指令として
    既存の台形プロファイル (TrapezoidProfile) に渡す形で作る。加減速の形は
    pv と同じ経路を通るので、6083h/6084h の意味が 2 か所に分かれない。
    """

    MODE_CODE = 1

    CW_NEW_SET_POINT = 1 << 4
    CW_CHANGE_IMMEDIATELY = 1 << 5
    CW_RELATIVE = 1 << 6
    CW_HALT = 1 << 8

    # 目標位置に「着いた」とみなす窓 [increment]。1 増分ぶんの丸めを許す。
    POSITION_WINDOW = 2

    def __init__(self):
        self._previous_new_set_point = False
        self._active_target = None      # 実行中の目標位置 (絶対, increment)
        self._pending_target = None     # IMM=0 のときに 1 段だけ保持する目標
        self._halted = False

    @property
    def mode_code(self):
        return self.MODE_CODE

    def _absolute_target(self, ctx, relative):
        target = int(ctx.params.target_position)
        if relative:
            return int(ctx.plant.position) + target
        return target

    def _handle_set_point(self, ctx, controlword):
        new_set_point = bool(controlword & self.CW_NEW_SET_POINT)
        rising = new_set_point and not self._previous_new_set_point
        self._previous_new_set_point = new_set_point
        if not rising:
            return

        relative = bool(controlword & self.CW_RELATIVE)
        immediately = bool(controlword & self.CW_CHANGE_IMMEDIATELY)
        target = self._absolute_target(ctx, relative)

        if self._active_target is None or immediately:
            self._active_target = target
            self._pending_target = None
        else:
            # Set of set-points: 現在の位置決めが終わってから開始する
            self._pending_target = target

    def _command_velocity(self, ctx):
        """残距離から、今出してよい速度 [internal] を返す。"""
        params = ctx.params
        remaining = self._active_target - int(ctx.plant.position)
        if abs(remaining) <= self.POSITION_WINDOW:
            return 0.0

        max_velocity = ctx.units.rpm_to_internal(params.profile_velocity_rpm)
        deceleration = ctx.units.rpm_to_internal(params.effective_deceleration_rpm_s)
        # 残距離で止まりきれる速度。v^2 = 2*a*s
        stoppable = (2.0 * deceleration * abs(remaining)) ** 0.5
        velocity = min(max_velocity, stoppable)
        return velocity if remaining > 0 else -velocity

    def step(self, dt, ctx):
        params = ctx.params
        controlword = ctx.state_machine.controlword
        self._halted = bool(controlword & self.CW_HALT)
        self._handle_set_point(ctx, controlword)

        ctx.profile.acceleration = ctx.units.rpm_to_internal(
            params.profile_acceleration_rpm_s)
        ctx.profile.deceleration = ctx.units.rpm_to_internal(
            params.effective_deceleration_rpm_s)

        if not ctx.state_machine.is_operation_enabled:
            self._active_target = None
            self._pending_target = None
            ctx.profile.set_target(0.0)
        elif self._halted:
            # HP-5143E 7.3.3: HALT=1 は 605Dh (Halt option code) に従って停止。
            # 605Dh は 1 (slow down ramp) のみ有効なので減速停止で固定。
            ctx.profile.set_target(0.0)
        elif self._active_target is None:
            ctx.profile.set_target(0.0)
        else:
            ctx.profile.set_target(self._command_velocity(ctx))

        ctx.profile.step(dt)
        ctx.plant.step(dt, ctx.profile.command)

        self._advance_set_points(ctx)

    def _advance_set_points(self, ctx):
        if self._active_target is None or self._halted:
            return
        arrived = (
            abs(self._active_target - int(ctx.plant.position)) <= self.POSITION_WINDOW
            and abs(ctx.plant.velocity) <= ctx.units.rpm_to_internal(
                ctx.params.velocity_threshold_rpm)
        )
        if not arrived:
            return
        if self._pending_target is not None:
            self._active_target, self._pending_target = self._pending_target, None
        else:
            self._active_target = None

    def apply_status_bits(self, ctx):
        if self._halted:
            # HALT=1 のときの bit10 は「モーターが停止した」の意味 (7.3.4)。
            ctx.state_machine.target_reached = (
                abs(ctx.units.internal_to_rpm(ctx.plant.velocity))
                <= ctx.params.velocity_threshold_rpm)
        else:
            ctx.state_machine.target_reached = (
                ctx.state_machine.is_operation_enabled
                and self._active_target is None
                and self._pending_target is None)

        # bit12 SPA: 受理した set-point を処理中かどうか。
        ctx.state_machine.operation_mode_specific_12 = (
            self._active_target is not None or self._pending_target is not None)


class ProfileTorqueMode(OperationMode):
    """Profile Torque Mode (tq)。HP-5143E 7.4 (p47-49)。

    6071h Target torque (0.1% 単位) を 6087h Torque slope (0.1%/s) の傾きで
    追い、6072h Max torque と 4032h のトルク制限値で頭打ちにする。
    Controlword bit8 HALT は「6087h の傾きでトルクを 0 へ落とす」。
    """

    MODE_CODE = 4

    CW_HALT = 1 << 8

    def __init__(self):
        self._demand = 0.0
        self._halted = False
        self._limited = False

    @property
    def mode_code(self):
        return self.MODE_CODE

    def _limit(self, ctx, value):
        params = ctx.params
        ceiling = min(params.max_torque_permille, params.direct_torque_limit_permille)
        if abs(value) > ceiling:
            self._limited = True
            return ceiling if value > 0 else -ceiling
        self._limited = False
        return value

    def step(self, dt, ctx):
        params = ctx.params
        controlword = ctx.state_machine.controlword
        self._halted = bool(controlword & self.CW_HALT)

        if not ctx.state_machine.is_operation_enabled:
            target = 0.0
        elif self._halted:
            target = 0.0
        else:
            target = float(params.target_torque)
        target = self._limit(ctx, target)

        slope = float(params.torque_slope)
        if slope <= 0.0:
            # 6087h = 0 (既定) は傾き無し = 即時反映として扱う。
            self._demand = target
        else:
            step_limit = slope * dt
            delta = target - self._demand
            if abs(delta) <= step_limit:
                self._demand = target
            else:
                self._demand += step_limit if delta > 0 else -step_limit

        if self._halted or not ctx.state_machine.is_operation_enabled:
            # HP-5143E 7.4.3 の HALT は 6087h の傾きでトルクを落とすが、
            # bit10 の意味は「モーターが停止した」であり、605Dh (Halt option
            # code = 1: slow down ramp) の減速で実際に止まるところまでが
            # 停止動作。トルクを抜くだけだと無負荷モデルでは永久に惰走する。
            ctx.profile.acceleration = ctx.units.rpm_to_internal(
                params.profile_acceleration_rpm_s)
            ctx.profile.deceleration = ctx.units.rpm_to_internal(
                params.effective_deceleration_rpm_s)
            ctx.profile.set_target(0.0)
            ctx.profile.step(dt)
            ctx.plant.step(dt, ctx.profile.command)
            ctx.plant.torque_permille = self._demand
            return

        max_velocity = ctx.units.rpm_to_internal(params.profile_velocity_rpm)
        ctx.plant.step_torque(dt, self._demand, max_velocity)
        # 速度指令 (606Bh) は tq では意味を持たないので実速度に合わせておく
        ctx.profile.reset(ctx.plant.velocity)

    @property
    def torque_demand(self):
        return int(round(self._demand))

    def apply_status_bits(self, ctx):
        if self._halted:
            ctx.state_machine.target_reached = (
                abs(ctx.units.internal_to_rpm(ctx.plant.velocity))
                <= ctx.params.velocity_threshold_rpm)
        else:
            ctx.state_machine.target_reached = (
                self.torque_demand == self._limit(ctx, float(ctx.params.target_torque)))
        ctx.state_machine.torque_limit_active = self._limited
        ctx.state_machine.operation_mode_specific_12 = False
        ctx.state_machine.operation_mode_specific_13 = False


class HomingMode(OperationMode):
    """Homing Mode (hm)。HP-5143E 7.5 (p50-57)。

    Controlword: bit4 HOS (Homing operation start)
    Statusword : bit10 TR / bit12 HA (Homing attained) / bit13 HE (Homing error)
      bit13/bit12/bit10 = 0/0/0 進行中、0/0/1 中断または未開始、
                          0/1/1 正常完了 (7.5.4 の表)

    サポートする方式 (7.5.5 実測):
      17 / 18 : リミットセンサ (RV-LS / FW-LS) で原点出し
      24 / 28 : HOME センサ (HOMES) で原点出し。24 は正方向、28 は負方向から
      35 / 37 : 現在位置を原点にする (35 と 37 は同一動作)
    index pulse (ZSG-N) を使う 1/2/8/12 とメーカ固有の -1 は未対応。
    """

    MODE_CODE = 6

    CW_HOMING_START = 1 << 4
    CW_HALT = 1 << 8

    # (方式 -> (探索方向, センサ名))
    SEARCH = {
        17: (-1, "rv_ls"),
        18: (+1, "fw_ls"),
        24: (+1, "home"),
        28: (-1, "home"),
    }
    CURRENT_POSITION_METHODS = (35, 37)

    # 状態
    IDLE = "idle"
    SEARCHING = "searching"      # センサへ向かう
    LEAVING = "leaving"          # センサから抜ける
    BACKING_OFF = "backing_off"  # 4169h ぶん戻る
    DONE = "done"

    def __init__(self):
        self._previous_start = False
        self._phase = self.IDLE
        self._attained = False
        self._error = False
        self._backoff_target = None

    @property
    def mode_code(self):
        return self.MODE_CODE

    def _sensor(self, ctx, name):
        return bool(getattr(ctx.params, "limit_inputs", {}).get(name, False))

    def _finish(self, ctx):
        ctx.plant.preset_position(int(ctx.params.home_offset))
        ctx.profile.reset(0.0)
        ctx.plant.velocity = 0.0
        self._phase = self.DONE
        self._attained = True
        ctx.params.on_homing_completed()

    def step(self, dt, ctx):
        params = ctx.params
        controlword = ctx.state_machine.controlword
        start = bool(controlword & self.CW_HOMING_START)
        rising = start and not self._previous_start
        self._previous_start = start

        ctx.profile.acceleration = ctx.units.rpm_to_internal(params.homing_acceleration_rpm_s)
        ctx.profile.deceleration = ctx.units.rpm_to_internal(params.homing_acceleration_rpm_s)

        if not ctx.state_machine.is_operation_enabled:
            self._phase = self.IDLE
            self._attained = False
            ctx.profile.set_target(0.0)
            ctx.profile.step(dt)
            ctx.plant.step(dt, ctx.profile.command)
            return

        if rising:
            self._attained = False
            self._error = False
            if params.homing_method in self.CURRENT_POSITION_METHODS:
                self._finish(ctx)
                return
            self._phase = self.SEARCHING

        if controlword & self.CW_HALT:
            ctx.profile.set_target(0.0)
        elif self._phase == self.SEARCHING:
            direction, sensor = self.SEARCH[params.homing_method]
            if self._sensor(ctx, sensor):
                self._phase = self.LEAVING
                ctx.profile.set_target(0.0)
            else:
                ctx.profile.set_target(
                    direction * ctx.units.rpm_to_internal(params.homing_speed_switch_rpm))
        elif self._phase == self.LEAVING:
            direction, sensor = self.SEARCH[params.homing_method]
            if self._sensor(ctx, sensor):
                # センサから抜けるまで逆方向へ
                ctx.profile.set_target(
                    -direction * ctx.units.rpm_to_internal(params.homing_speed_zero_rpm))
            else:
                # 抜けた。4169h (2 センサ原点復帰の戻りステップ数) ぶん進んで停止
                steps = int(params.homing_backward_steps)
                self._backoff_target = int(ctx.plant.position) - direction * steps
                self._phase = self.BACKING_OFF
        elif self._phase == self.BACKING_OFF:
            remaining = self._backoff_target - int(ctx.plant.position)
            threshold = ctx.units.rpm_to_internal(params.velocity_threshold_rpm)
            if abs(remaining) <= 2:
                # 戻り量に着いた (4169h が 0 なら最初からここ)。停止したら完了。
                ctx.profile.set_target(0.0)
                if abs(ctx.plant.velocity) <= threshold:
                    self._finish(ctx)
                    return
            else:
                # 残距離で止まりきれる速度まで落として寄せる (pp と同じ考え方)。
                # 一定速で突っ込むと目標を通り過ぎて振動する。
                speed = ctx.units.rpm_to_internal(params.homing_speed_zero_rpm)
                deceleration = ctx.units.rpm_to_internal(
                    params.homing_acceleration_rpm_s)
                stoppable = (2.0 * deceleration * abs(remaining)) ** 0.5
                velocity = min(speed, stoppable)
                ctx.profile.set_target(velocity if remaining > 0 else -velocity)
        else:
            ctx.profile.set_target(0.0)

        ctx.profile.step(dt)
        ctx.plant.step(dt, ctx.profile.command)

    def apply_status_bits(self, ctx):
        stopped = (
            abs(ctx.units.internal_to_rpm(ctx.plant.velocity))
            <= ctx.params.velocity_threshold_rpm)
        in_progress = self._phase in (self.SEARCHING, self.LEAVING, self.BACKING_OFF)
        # 7.5.4 の表: 進行中は bit10=0、完了で bit12=bit10=1
        ctx.state_machine.target_reached = (not in_progress) and stopped
        ctx.state_machine.operation_mode_specific_12 = self._attained
        ctx.state_machine.operation_mode_specific_13 = self._error
        ctx.state_machine.torque_limit_active = False
