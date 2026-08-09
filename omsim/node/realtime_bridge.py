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
import logging

import can

logger = logging.getLogger(__name__)

# canopen.NmtBase.state は文字列を返すため、node guarding 応答用に数値へ
# 変換する対応表をこちら側で持つ (canopen の private 属性に依存しないため)。
# 4.2.1 実測: Operational=5 / Stopped=4 / Pre-operational=127。
_NMT_STATE_TO_CODE = {
    "OPERATIONAL": 0x05,
    "STOPPED": 0x04,
    "PRE-OPERATIONAL": 0x7F,
}


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


def _encode_tpdo(od, model, mapping):
    chunks = []
    for entry in mapping.entries:
        variable = _od_variable(od, entry.index, entry.sub)
        value = model.read_object(entry.index, entry.sub)
        chunks.append(variable.encode_raw(value))
    return b"".join(chunks)


class _TpdoRuntime(object):
    """トランスポート側の送信管理状態。DriverModel には持たせない
    (デバイスの状態ではなく、送信タイミングの内部管理だけのため)。"""

    def __init__(self):
        self.last_bytes = None
        self.sync_count = 0
        self.pending_change = False
        self.last_transmit_time = None


class _SyncProducerState(object):
    def __init__(self):
        self.next_due = None


class _NodeListener(can.Listener):
    """1 ノードぶんの RPDO / SYNC 受信を捌く。node guarding / Heartbeat
    consumer の受信は Task 11 でこのクラスに追加する。"""

    def __init__(self, node, model, od, queue, sync_counter):
        self._node = node
        self._model = model
        self._od = od
        self._queue = queue
        self._sync_counter = sync_counter
        self._guard_toggle = False

    def on_message_received(self, msg):
        if getattr(msg, "is_error_frame", False):
            return
        can_id = msg.arbitration_id
        is_rtr = getattr(msg, "is_remote_frame", False)

        if not is_rtr and can_id == (self._model.sync_cob_id & 0x7FF):
            self._sync_counter.notify()
            return

        if is_rtr and can_id == 0x700 + self._model.node_id:
            self._respond_node_guard()
            return

        watch_node_id = self._model.heartbeat_consumer_node_id
        if not is_rtr and watch_node_id and can_id == 0x700 + watch_node_id:
            # Heartbeat/boot-up は 1 バイトの NMT 状態コードのみを積む
            # (4.2.2/4.3 実測)。sim_time は step() 側で管理しているため、
            # ここでは「今受信した」ことだけを model に伝える。
            self._model.on_heartbeat_received(watch_node_id, self._model.sim_time)
            return

        if not is_rtr:
            self._handle_rpdo(can_id, bytes(msg.data))

    def _respond_node_guard(self):
        state_code = _NMT_STATE_TO_CODE.get(self._node.nmt.state)
        if state_code is None:
            return
        byte0 = (0x80 if self._guard_toggle else 0x00) | state_code
        self._guard_toggle = not self._guard_toggle
        self._node.network.send_message(0x700 + self._model.node_id, [byte0])

    def _handle_rpdo(self, can_id, data):
        for slot in range(4):
            comm = self._model.rpdo_comm[slot]
            if comm.valid and comm.cob_id == can_id:
                trigger = "sync" if comm.transmission_type == 0x00 else "immediate"
                mapping = self._model.rpdo_mapping[slot]
                try:
                    decoded = _decode_rpdo(self._od, data, mapping)
                except Exception as err:
                    # マッピングよりデータ長が短い等、壊れたフレームは捨てる。
                    # ここで例外を漏らすと python-can の Notifier が受信
                    # スレッドごと止めてしまい、バス上の 1 フレームで以後の
                    # 全受信 (SDO も含む) が死ぬ。黙って捨てずログに出す。
                    logger.warning(
                        "node%d: RPDO%d (COB-ID %03Xh, %d バイト) を解釈できません: %s",
                        self._model.node_id, slot + 1, can_id, len(data), err)
                    return
                for index, sub, value in decoded:
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
        self._tpdo_runtime = {}  # node_id -> [runtime_slot0..3]
        self._sync_producer = {}  # node_id -> _SyncProducerState

    def _make_listener(self, node, model, od, queue, sync_counter):
        return _NodeListener(node, model, od, queue, sync_counter)

    def _make_tpdo_runtime(self):
        return [_TpdoRuntime() for _ in range(4)]

    def attach(self, node, model, od, queue, sync_counter):
        """node が Network に登録済みの状態で呼ぶ。"""
        listener = self._make_listener(node, model, od, queue, sync_counter)
        self._listeners[model.node_id] = listener
        self._tpdo_runtime[model.node_id] = self._make_tpdo_runtime()
        self._sync_producer[model.node_id] = _SyncProducerState()
        network = node.network
        network.listeners.append(listener)
        notifier = getattr(network, "notifier", None)
        if notifier is not None:
            notifier.add_listener(listener)

    def _send_tpdo(self, network, model, od, comm, mapping, runtime, sim_time):
        data = _encode_tpdo(od, model, mapping)
        network.send_message(comm.cob_id, data)
        runtime.last_bytes = data
        runtime.pending_change = False
        runtime.last_transmit_time = sim_time

    def on_sync(self, node_id, model, network, od, sim_time):
        """SYNC 受信のたびに呼ぶ: 同期系 TPDO (0x00/0x01-0xF0/0xFC) を進める。"""
        runtimes = self._tpdo_runtime[node_id]
        for slot, comm in enumerate(model.tpdo_comm):
            if not comm.valid:
                continue
            mapping = model.tpdo_mapping[slot]
            runtime = runtimes[slot]
            tt = comm.transmission_type
            if tt == 0x00:
                current = _encode_tpdo(od, model, mapping)
                if runtime.last_bytes is None or current != runtime.last_bytes:
                    runtime.pending_change = True
                if runtime.pending_change:
                    self._send_tpdo(
                        network, model, od, comm, mapping, runtime, sim_time)
            elif 0x01 <= tt <= 0xF0:
                runtime.sync_count += 1
                if runtime.sync_count >= tt:
                    self._send_tpdo(
                        network, model, od, comm, mapping, runtime, sim_time)
                    runtime.sync_count = 0
            elif tt == 0xFC:
                # SYNC でサンプルし、RTR 受信時に送信する (送信は Task 11 の
                # RTR 応答側で行う)。ここではサンプルだけ取る。
                runtime.last_bytes = _encode_tpdo(od, model, mapping)

    def _maybe_send_sync(self, node_id, model, network, sim_time):
        """SYNC producer (1005h bit30 + 1006h 周期) が有効なら SYNC を送る。"""
        state = self._sync_producer.setdefault(node_id, _SyncProducerState())
        if not (model.sync_producer_enabled and model.sync_period_us > 0):
            state.next_due = None
            return
        period_seconds = model.sync_period_us / 1e6
        if state.next_due is None:
            state.next_due = sim_time
        if sim_time >= state.next_due:
            network.send_message(model.sync_cob_id & 0x7FF, [])
            state.next_due = sim_time + period_seconds

    def step(self, node_id, model, network, od, sim_time):
        """1ms ごとに呼ぶ: SYNC producer と、非同期系 TPDO (0xFE/0xFF) の
        inhibit/event timer を判定する。"""
        self._maybe_send_sync(node_id, model, network, sim_time)
        runtimes = self._tpdo_runtime[node_id]
        for slot, comm in enumerate(model.tpdo_comm):
            if not comm.valid or comm.transmission_type not in (0xFE, 0xFF):
                continue
            mapping = model.tpdo_mapping[slot]
            runtime = runtimes[slot]
            current = _encode_tpdo(od, model, mapping)
            if runtime.last_bytes is None or current != runtime.last_bytes:
                runtime.pending_change = True
            if runtime.last_transmit_time is None:
                self._send_tpdo(network, model, od, comm, mapping, runtime, sim_time)
                continue
            elapsed = sim_time - runtime.last_transmit_time
            inhibit_seconds = comm.inhibit_time_100us * 100e-6
            if runtime.pending_change and elapsed >= inhibit_seconds:
                self._send_tpdo(network, model, od, comm, mapping, runtime, sim_time)
                continue
            if comm.event_timer_ms and elapsed >= comm.event_timer_ms / 1000.0:
                self._send_tpdo(network, model, od, comm, mapping, runtime, sim_time)
