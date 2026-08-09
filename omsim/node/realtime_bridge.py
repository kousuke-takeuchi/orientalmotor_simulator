"""PDO (RPDO 受信 / TPDO 送信) と SYNC を CAN バスへ配線する。

canopen.LocalNode は SDO/NMT/EMCY のみ扱い、PDO/SYNC の送受信は自前で
行う。canopen.pdo サブモジュールは SDO クライアント経由で自分自身の
設定を読み書きする設計 (RemoteNode を主眼にした実装) で、プロセス内で
DriverModel と直結しているこのノードの使い方とは噛み合わないため使わない。

Recorder.FrameListener と同じパターンで can.Listener を直接実装する。
値のエンコード/デコードは自前でビット演算をせず、canopen の
ObjectDictionary が持つ ODVariable.encode_raw()/decode_raw() をそのまま
使う (符号付き整数の扱いを canopen 本体と一致させるため)。
"""
import can


def _od_variable(od, index, sub):
    obj = od[index]
    if hasattr(obj, "subindices"):
        return obj[sub]
    return obj


def _decode_rpdo(od, data, mapping):
    """マッピングに従って data を分解し [(index, sub, value), ...] を返す。

    バイト境界のみ対応 (Task 7 の書込みバリデーションで保証済み)。
    """
    decoded = []
    offset_bytes = 0
    for entry in mapping.entries:
        length_bytes = entry.length_bits // 8
        variable = _od_variable(od, entry.index, entry.sub)
        chunk = bytes(data[offset_bytes:offset_bytes + length_bytes])
        value = variable.decode_raw(chunk)
        decoded.append((entry.index, entry.sub, value))
        offset_bytes += length_bytes
    return decoded


class _NodeListener(can.Listener):
    """1 ノードぶんの RPDO / SYNC 受信を捌く。node guarding / Heartbeat
    consumer の受信は Task 11 でこのクラスに追加する。"""

    def __init__(self, model, od, queue, sync_counter):
        self._model = model
        self._od = od
        self._queue = queue
        self._sync_counter = sync_counter

    def on_message_received(self, msg):
        if getattr(msg, "is_error_frame", False):
            return
        can_id = msg.arbitration_id
        is_rtr = getattr(msg, "is_remote_frame", False)

        if not is_rtr and can_id == (self._model.sync_cob_id & 0x7FF):
            self._sync_counter.notify()
            return

        if not is_rtr:
            self._handle_rpdo(can_id, bytes(msg.data))

    def _handle_rpdo(self, can_id, data):
        for slot in range(4):
            comm = self._model.rpdo_comm[slot]
            if comm.valid and comm.cob_id == can_id:
                trigger = "sync" if comm.transmission_type == 0x00 else "immediate"
                mapping = self._model.rpdo_mapping[slot]
                for index, sub, value in _decode_rpdo(self._od, data, mapping):
                    self._queue.put(index, sub, value, trigger=trigger)
                return

    def on_error(self, exc):
        # 個別フレームのエラーで受信スレッドを止めない
        # (Recorder.FrameListener と同じ方針)。
        pass


class RealtimeBridge(object):
    """NodeManager が全ノードぶん共有して使う。"""

    def __init__(self):
        self._listeners = {}

    def _make_listener(self, model, od, queue, sync_counter, node_id):
        return _NodeListener(model, od, queue, sync_counter)

    def attach(self, node, model, od, queue, sync_counter):
        """node が Network に登録済みの状態で呼ぶ。"""
        listener = self._make_listener(model, od, queue, sync_counter, model.node_id)
        self._listeners[model.node_id] = listener
        network = node.network
        network.listeners.append(listener)
        notifier = getattr(network, "notifier", None)
        if notifier is not None:
            notifier.add_listener(listener)
