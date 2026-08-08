"""モーターの物理モデル。指令速度への 1 次遅れ追従 + 位置積分 + トルク推定。

設計書 5.6 のとおり、実機のトルク値と一致させることは目的ではない。
加速中にトルクが増え、定常では負荷分に落ち着くという挙動を再現する。
"""


class MotorPlant(object):
    def __init__(self, time_constant=0.02, load_torque_permille=0.0, inertia_gain=1e-4):
        self.time_constant = float(time_constant)
        self.load_torque_permille = float(load_torque_permille)
        self.inertia_gain = float(inertia_gain)
        self.excited = False
        self.velocity = 0.0
        self.torque_permille = 0.0
        self._position = 0.0

    @property
    def position(self):
        return int(self._position)

    def preset_position(self, value):
        self._position = float(value)

    def reset(self):
        self.velocity = 0.0
        self.torque_permille = 0.0
        self._position = 0.0

    def step(self, dt, command_velocity):
        target = float(command_velocity) if self.excited else 0.0
        previous = self.velocity

        if self.time_constant <= 0.0:
            self.velocity = target
        else:
            alpha = min(1.0, dt / self.time_constant)
            self.velocity += (target - self.velocity) * alpha

        self._position += self.velocity * dt

        if self.excited:
            acceleration = (self.velocity - previous) / dt if dt > 0.0 else 0.0
            self.torque_permille = self.inertia_gain * acceleration + self.load_torque_permille
        else:
            self.torque_permille = 0.0
