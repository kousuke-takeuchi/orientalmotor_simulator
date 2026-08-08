"""台形加減速の指令速度生成。単位は increment/s、加減速度は increment/s^2。

停止方法の詳細は HP-5141J 第1章3節「停止動作」(p34)。ここでは加減速の骨格のみを持つ。
"""


class TrapezoidProfile(object):
    def __init__(self, acceleration=1000.0, deceleration=1000.0):
        self.acceleration = float(acceleration)
        self.deceleration = float(deceleration)
        self.command = 0.0
        self.target = 0.0

    @property
    def at_target(self):
        return self.command == self.target

    def set_target(self, value):
        self.target = float(value)

    def reset(self, command=0.0):
        self.command = float(command)
        self.target = float(command)

    def step(self, dt):
        if self.command == self.target:
            return self.command

        # 符号反転をまたぐ場合は 0 で折り返す
        crossing_zero = self.command * self.target < 0.0
        waypoint = 0.0 if crossing_zero else self.target

        if abs(waypoint) > abs(self.command) and self.command * waypoint >= 0.0:
            rate = self.acceleration
        else:
            rate = self.deceleration

        delta = rate * dt
        if waypoint > self.command:
            self.command = min(self.command + delta, waypoint)
        else:
            self.command = max(self.command - delta, waypoint)
        return self.command
