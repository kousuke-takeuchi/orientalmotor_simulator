"""Web へ配る状態スナップショットと CAN フレームを保持する。

FastAPI には依存しない。Web が無くても単体テストできるようにするため。
"""
import collections


class SnapshotHub(object):
    def __init__(self, manager, recorder, history_size=600):
        self._manager = manager
        self._recorder = recorder
        self._history = collections.deque(maxlen=history_size)

    def capture(self):
        snapshot = self._manager.snapshot()
        self._history.append(snapshot)
        return snapshot

    def latest(self):
        if not self._history:
            return None
        return self._history[-1]

    def history(self, limit=None):
        items = list(self._history)
        if limit is None:
            return items
        return items[-limit:]

    def frames(self, limit=100):
        return self._recorder.recent_frames(limit=limit)

    # --- CN4 の配線 / 安全リレー ---
    #
    # ここだけは読み取り専用の原則から外れ、シミュレーション側の状態を
    # 書き換える。「配線を変えて挙動を比べる」ことが目的の操作卓であり、
    # CAN 上には現れない物理配線を触る手段が他に無いため。

    def wiring(self):
        manager = self._manager
        hwto1_on, hwto2_on = manager.wiring.hwto_inputs(manager.relay_energized)
        described = manager.wiring.describe()
        described["preset"] = manager.wiring.preset_name()
        described["relay"] = manager.relay_energized
        described["inputs"] = {"hwto1_on": hwto1_on, "hwto2_on": hwto2_on}
        return described

    def set_wiring(self, preset=None, hwto1=None, hwto2=None, relay=None):
        """不正な値は Cn4Wiring が WiringError を投げる (ここでは握らない)。"""
        from omsim.sim.wiring import Cn4Wiring

        manager = self._manager
        if preset is not None:
            manager.wiring = Cn4Wiring.preset(preset)
        if hwto1 is not None or hwto2 is not None:
            manager.wiring = Cn4Wiring(
                hwto1=hwto1 if hwto1 is not None else manager.wiring.hwto1,
                hwto2=hwto2 if hwto2 is not None else manager.wiring.hwto2)
        if relay is not None:
            manager.relay_energized = bool(relay)
        return self.wiring()

    def payload(self, frame_limit=50):
        snapshot = self.latest()
        return {
            "sim_time": snapshot["sim_time"] if snapshot else 0.0,
            "nodes": snapshot["nodes"] if snapshot else {},
            "frames": self.frames(limit=frame_limit),
        }
