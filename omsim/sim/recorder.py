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


class FrameListener(object):
    """python-can の Listener。canopen.Network.listeners に載せる。"""

    def __init__(self, recorder, clock):
        self._recorder = recorder
        self._clock = clock

    def on_message_received(self, msg):
        if getattr(msg, "is_error_frame", False):
            return
        self._recorder.frame("bus", msg.arbitration_id, bytes(msg.data), self._clock.now)

    def on_error(self, exc):
        pass

    def stop(self):
        pass


def attach_recorder(network, recorder, clock):
    listener = FrameListener(recorder, clock)
    network.listeners.append(listener)
    notifier = getattr(network, "notifier", None)
    if notifier is not None:
        # python-can 4.5.0 の Notifier は __init__ で listeners のコピーを取るため、
        # connect() 後に network.listeners へ append しただけでは効かない。
        notifier.add_listener(listener)
    return listener
