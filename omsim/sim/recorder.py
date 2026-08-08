"""CAN フレームと状態スナップショットを jsonl に記録する。"""
import collections
import json

from omsim.sim.decode import describe_frame


class Recorder(object):
    def __init__(self, path, buffer_size=2000):
        self._handle = open(path, "w", encoding="utf-8") if path else None
        self._buffer = collections.deque(maxlen=buffer_size)

    def frame(self, direction, can_id, data, sim_time):
        record = {
            "kind": "frame",
            "t": sim_time,
            "dir": direction,
            "can_id": can_id,
            "data": bytes(data).hex(),
            "text": describe_frame(can_id, data),
        }
        self._buffer.append(record)
        self._write(record)

    def state(self, snapshot):
        record = {"kind": "state", "t": snapshot.get("sim_time", 0.0), "snapshot": snapshot}
        self._write(record)

    def recent_frames(self, limit=100):
        items = list(self._buffer)
        return items[-limit:]

    def close(self):
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def _write(self, record):
        if self._handle is not None:
            self._handle.write(json.dumps(record, default=str) + "\n")
            self._handle.flush()
