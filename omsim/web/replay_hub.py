"""記録の再生を Web へ配る hub。SnapshotHub と同じ口を持つ。

シミュレーションを進める口は持たない (再生は読み取り専用)。
"""
from omsim.sim.wiring import WiringError


class ReplayHub(object):
    def __init__(self, recording):
        self._recording = recording
        self.position = 0.0
        self.playing = False

    # --- SnapshotHub と同じ口 ---

    def payload(self, frame_limit=50):
        return self._recording.payload_at(self.position, frame_limit=frame_limit)

    def capture(self):
        """再生中は「進める」概念が無いので何もしない。

        Web の配信ループが定期的に呼ぶため、例外にはしない。
        """
        return None

    def wiring(self):
        raise WiringError("再生中は配線を読めません (記録には含まれていません)")

    def set_wiring(self, **kwargs):
        raise WiringError("再生は読み取り専用です。配線や安全リレーは操作できません")

    # --- 再生の操作 ---

    def state(self):
        return {
            "position": self.position,
            "duration": self._recording.duration,
            "playing": self.playing,
            "broken_lines": self._recording.broken_lines,
        }

    def seek(self, seconds):
        self.position = max(0.0, min(float(seconds), self._recording.duration))
        return self.state()

    def set_playing(self, playing):
        self.playing = bool(playing)
        return self.state()

    def advance(self, seconds):
        if self.playing:
            self.seek(self.position + seconds)
        return self.state()
