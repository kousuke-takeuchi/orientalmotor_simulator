"""CAN フレームと状態スナップショットを jsonl に記録する。"""
import collections
import json
import logging
import threading

import can

from omsim.sim.decode import describe_frame

logger = logging.getLogger(__name__)


class Recorder(object):
    def __init__(self, path, buffer_size=2000):
        self._handle = open(path, "w", encoding="utf-8") if path else None
        self._buffer = collections.deque(maxlen=buffer_size)
        self._lock = threading.Lock()

    def frame(self, direction, can_id, data, sim_time):
        record = {
            "kind": "frame",
            "t": sim_time,
            "dir": direction,
            "can_id": can_id,
            "data": bytes(data).hex(),
            "text": describe_frame(can_id, data),
        }
        with self._lock:
            self._buffer.append(record)
        self._write(record)

    def state(self, snapshot):
        record = {"kind": "state", "t": snapshot.get("sim_time", 0.0), "snapshot": snapshot}
        self._write(record)

    def recent_frames(self, limit=100):
        with self._lock:
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


class FrameListener(can.Listener):
    """python-can の Listener。canopen.Network.listeners に載せる。

    python-can 4.5.0 の Notifier は受信のたびに listener(msg) という
    呼び出し可能形式でリスナーを呼ぶ（listener.on_message_received(msg) では
    ない）。can.Listener を継承していないと __call__ を持たず
    TypeError になって受信スレッドごと止まる（実機で発見されたバグ）。
    """

    def __init__(self, recorder, clock):
        self._recorder = recorder
        self._clock = clock

    def on_message_received(self, msg):
        if getattr(msg, "is_error_frame", False):
            return
        self._recorder.frame("bus", msg.arbitration_id, bytes(msg.data), self._clock.now)

    def on_error(self, exc):
        # 受信スレッドを落とさないよう握りつぶす。基底の can.Listener.on_error は
        # NotImplementedError を投げる実装のため、オーバーライドしないと
        # 個別のバスエラーで Notifier のスレッド自体が停止してしまう。
        logger.error("CAN bus error: %s", exc, exc_info=True)


def attach_recorder(network, recorder, clock):
    listener = FrameListener(recorder, clock)
    network.listeners.append(listener)
    notifier = getattr(network, "notifier", None)
    if notifier is not None:
        # python-can 4.5.0 の Notifier は __init__ で listeners のコピーを取るため、
        # connect() 後に network.listeners へ append しただけでは効かない。
        notifier.add_listener(listener)
    _wrap_bus_send_for_tx_logging(network, recorder, clock)
    return listener


def _wrap_bus_send_for_tx_logging(network, recorder, clock):
    """自ノードの送信フレームも CAN ログに載せる。

    SocketCAN は receive_own_messages が既定 False のため、Notifier
    (受信側) には自分の送信が返ってこない。SDO 応答・boot-up・
    Heartbeat・EMCY、そして P3 で追加する PDO・SYNC・node guarding
    応答は全て最終的に network.bus.send() を通るため、送信元コードを
    個別に触らず、この 1 箇所をラップするだけで将来の送信経路追加にも
    自動的に追従する。
    """
    bus = getattr(network, "bus", None)
    if bus is None or getattr(bus, "_omsim_tx_wrapped", False):
        return
    original_send = bus.send

    def send_and_record(msg, *args, **kwargs):
        original_send(msg, *args, **kwargs)
        if not getattr(msg, "is_remote_frame", False):
            recorder.frame("tx", msg.arbitration_id, bytes(msg.data), clock.now)

    bus.send = send_and_record
    bus._omsim_tx_wrapped = True
