import can

from omsim.driver.model import DriverModel
from omsim.node.eds import DEFAULT_EDS_PATH, load_eds
from omsim.node.realtime_bridge import RealtimeBridge
from omsim.sim.command_queue import CommandQueue
from omsim.sim.sync_counter import SyncCounter


class FakeNmt(object):
    def __init__(self, state="PRE-OPERATIONAL"):
        self.state = state


class FakeNode(object):
    def __init__(self, state="PRE-OPERATIONAL"):
        self.nmt = FakeNmt(state)
        self.network = None  # node guarding のテストでは FakeNetwork を後付けする


def make_listener(node_id=1):
    od = load_eds(DEFAULT_EDS_PATH)
    model = DriverModel(node_id=node_id)
    queue = CommandQueue()
    sync_counter = SyncCounter()
    bridge = RealtimeBridge()
    node = FakeNode()
    listener = bridge._make_listener(node, model, od, queue, sync_counter)
    return listener, model, queue, sync_counter, node


def test_rpdo1_frame_queues_controlword_as_immediate():
    listener, model, queue, _sync, _node = make_listener()
    msg = can.Message(arbitration_id=0x201, data=[0x07, 0x00], is_extended_id=False)
    listener.on_message_received(msg)
    assert queue.pending_count() == 1
    queue.drain(model)
    assert model.read_object(0x6040) == 0x0007


def test_rpdo2_frame_decodes_two_mapped_objects():
    listener, model, queue, _sync, _node = make_listener()
    # RPDO2 既定マッピング: 6040h(16bit) + 6060h(8bit)
    msg = can.Message(arbitration_id=0x301, data=[0x0F, 0x00, 0x03], is_extended_id=False)
    listener.on_message_received(msg)
    queue.drain(model)
    assert model.read_object(0x6040) == 0x000F


def test_sync_transmission_type_rpdo_is_queued_as_sync_trigger():
    listener, model, queue, _sync, _node = make_listener()
    model.write_object(0x1400, 2, 0x00)  # SYNC 反映へ変更
    before = model.read_object(0x6040)
    msg = can.Message(arbitration_id=0x201, data=[0x07, 0x00], is_extended_id=False)
    listener.on_message_received(msg)
    queue.drain(model, sync_received=False)
    assert model.read_object(0x6040) == before  # まだ変わらない (SYNC 待ち)
    queue.drain(model, sync_received=True)
    assert model.read_object(0x6040) == 0x0007


def test_disabled_rpdo_is_ignored():
    listener, model, queue, _sync, _node = make_listener()
    model.write_object(0x1400, 1, model.rpdo_comm[0].cob_id | (1 << 31))  # 無効化
    msg = can.Message(arbitration_id=0x201, data=[0x07, 0x00], is_extended_id=False)
    listener.on_message_received(msg)
    assert queue.pending_count() == 0


def test_unrelated_cob_id_is_ignored():
    listener, model, queue, _sync, _node = make_listener()
    msg = can.Message(arbitration_id=0x999, data=[0x07, 0x00], is_extended_id=False)
    listener.on_message_received(msg)
    assert queue.pending_count() == 0


def test_sync_frame_notifies_sync_counter():
    listener, _model, _queue, sync_counter, _node = make_listener()
    msg = can.Message(arbitration_id=0x80, data=[], is_extended_id=False)
    listener.on_message_received(msg)
    assert sync_counter.take() == 1


def test_remote_frame_at_sync_cob_id_is_not_treated_as_sync():
    listener, _model, _queue, sync_counter, _node = make_listener()
    msg = can.Message(arbitration_id=0x80, data=[], is_extended_id=False,
                      is_remote_frame=True)
    listener.on_message_received(msg)
    assert sync_counter.take() == 0


class FakeNetwork(object):
    def __init__(self):
        self.sent = []

    def send_message(self, cob_id, data):
        self.sent.append((cob_id, bytes(data)))


def make_bridge_and_model(node_id=1):
    od = load_eds(DEFAULT_EDS_PATH)
    model = DriverModel(node_id=node_id)
    bridge = RealtimeBridge()
    bridge._tpdo_runtime[node_id] = bridge._make_tpdo_runtime()
    return bridge, model, od


def _sent_on(network, cob_id):
    return [s for s in network.sent if s[0] == cob_id]


def test_tpdo1_sync_acyclic_sends_once_after_a_change():
    # TPDO1 の既定 transmission type は 255 (非同期) なので、SYNC 系の
    # 挙動を見るには 0x00 (値が変化していれば次の SYNC で送信) にする。
    bridge, model, od = make_bridge_and_model()
    network = FakeNetwork()
    model.write_object(0x1800, 2, 0x00)
    model.write_object(0x6040, 0, 0x0006)  # statusword を変化させる
    bridge.on_sync(1, model, network, od, sim_time=0.0)
    assert len(_sent_on(network, model.tpdo_comm[0].cob_id)) == 1


def test_tpdo1_sync_acyclic_does_not_resend_without_a_change():
    bridge, model, od = make_bridge_and_model()
    network = FakeNetwork()
    model.write_object(0x1800, 2, 0x00)
    bridge.on_sync(1, model, network, od, sim_time=0.0)
    first_count = len(_sent_on(network, model.tpdo_comm[0].cob_id))
    bridge.on_sync(1, model, network, od, sim_time=0.001)
    # 変化なしなので増えない
    assert len(_sent_on(network, model.tpdo_comm[0].cob_id)) == first_count


def test_tpdo3_cyclic_nth_sync_sends_every_n_syncs():
    bridge, model, od = make_bridge_and_model()
    network = FakeNetwork()
    model.write_object(0x1802, 2, 3)  # 3 回目の SYNC ごとに送信
    for _ in range(2):
        bridge.on_sync(1, model, network, od, sim_time=0.0)
    tpdo3 = [s for s in network.sent if s[0] == model.tpdo_comm[2].cob_id]
    assert len(tpdo3) == 0
    bridge.on_sync(1, model, network, od, sim_time=0.0)
    tpdo3 = [s for s in network.sent if s[0] == model.tpdo_comm[2].cob_id]
    assert len(tpdo3) == 1


def test_event_driven_tpdo_sends_after_inhibit_time_elapses():
    bridge, model, od = make_bridge_and_model()
    network = FakeNetwork()
    model.write_object(0x1800, 3, 10)  # inhibit = 10 * 100us = 1ms
    bridge.step(1, model, network, od, sim_time=0.0)  # 初回送信
    initial = len(network.sent)
    model.write_object(0x6040, 0, 0x0006)  # 変化させる
    bridge.step(1, model, network, od, sim_time=0.0005)  # inhibit 未経過
    assert len(network.sent) == initial
    bridge.step(1, model, network, od, sim_time=0.0011)  # inhibit 経過
    assert len(network.sent) == initial + 1


def test_event_timer_resends_even_without_a_change():
    bridge, model, od = make_bridge_and_model()
    network = FakeNetwork()
    model.write_object(0x1800, 5, 5)  # event timer = 5ms
    bridge.step(1, model, network, od, sim_time=0.0)
    initial = len(network.sent)
    bridge.step(1, model, network, od, sim_time=0.006)  # 変化無しでも 5ms 経過
    assert len(network.sent) == initial + 1


def test_disabled_tpdo_never_sends():
    bridge, model, od = make_bridge_and_model()
    network = FakeNetwork()
    for index in (0x1800, 0x1801, 0x1802, 0x1803):
        slot = index - 0x1800
        model.write_object(index, 1, model.tpdo_comm[slot].cob_id | (1 << 31))
    bridge.on_sync(1, model, network, od, sim_time=0.0)
    bridge.step(1, model, network, od, sim_time=0.0)
    assert network.sent == []


def test_node_guard_rtr_responds_with_toggled_state_byte():
    listener, _model, _queue, _sync, node = make_listener()
    node.network = FakeNetwork()
    listener._respond_node_guard()
    listener._respond_node_guard()
    assert len(node.network.sent) == 2
    first_byte = node.network.sent[0][1][0]
    second_byte = node.network.sent[1][1][0]
    assert (first_byte & 0x7F) == 0x7F  # PRE-OPERATIONAL
    assert (first_byte & 0x80) != (second_byte & 0x80)


def test_heartbeat_from_watched_node_notifies_the_model():
    listener, model, _queue, _sync, _node = make_listener()
    model.write_object(0x1016, 1, (2 << 16) | 500)
    msg = can.Message(arbitration_id=0x702, data=[0x7F], is_extended_id=False)
    listener.on_message_received(msg)
    assert model._heartbeat_consumer_reference_time == model.sim_time
