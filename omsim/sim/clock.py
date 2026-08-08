"""1ms 固定ステップの時計。now は tick_count から計算し、加算誤差を溜めない。"""
import time


class SimClock(object):
    STEP_SECONDS = 0.001

    def __init__(self, realtime=True):
        self.realtime = realtime
        self.tick_count = 0
        self._wall_start = time.monotonic()

    @property
    def now(self):
        return self.tick_count * self.STEP_SECONDS

    def advance(self):
        self.tick_count += 1
        if self.realtime:
            target = self._wall_start + self.now
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        return self.STEP_SECONDS

    def advance_for(self, seconds):
        steps = int(round(seconds / self.STEP_SECONDS))
        for _ in range(steps):
            self.advance()
        return steps
