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
            else:
                # 遅延している間 sleep を一切呼ばないと、シミュレーション
                # ループが完全な busy loop になって GIL を独占し続け、
                # CAN 受信スレッドや uvicorn スレッドが飢餓状態になる
                # (P2 最終レビュー指摘)。time.sleep(0) は OS に一度制御を
                # 返すだけで、追いつく速度への影響はほぼ無い。
                time.sleep(0)
        return self.STEP_SECONDS

    def advance_for(self, seconds):
        steps = int(round(seconds / self.STEP_SECONDS))
        for _ in range(steps):
            self.advance()
        return steps
