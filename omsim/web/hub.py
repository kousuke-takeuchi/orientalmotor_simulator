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

    def payload(self, frame_limit=50):
        snapshot = self.latest()
        return {
            "sim_time": snapshot["sim_time"] if snapshot else 0.0,
            "nodes": snapshot["nodes"] if snapshot else {},
            "frames": self.frames(limit=frame_limit),
        }
