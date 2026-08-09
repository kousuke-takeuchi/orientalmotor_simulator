"""運転モード。CiA402 の Modes of operation (6060h) ごとの振る舞いを持つ。

DriverModel は「どのモードか」を選ぶだけにして、モードごとの制御則と
Statusword のモード固有ビット (bit10/12/13) の意味づけをここに閉じ込める。
P4 で pp / hm / tq を足すときは、このクラスを増やすだけで済む形にしてある。

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
            ctx.profile.set_target(ctx.units.rpm_to_internal(params.target_velocity_rpm))
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
