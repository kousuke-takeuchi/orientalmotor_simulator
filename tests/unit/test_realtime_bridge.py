import can

from omsim.driver.model import DriverModel
from omsim.node.eds import DEFAULT_EDS_PATH, load_eds
from omsim.node.realtime_bridge import RealtimeBridge
from omsim.sim.command_queue import CommandQueue
from omsim.sim.sync_counter import SyncCounter


def make_listener(node_id=1):
    od = load_eds(DEFAULT_EDS_PATH)
    model = DriverModel(node_id=node_id)
    queue = CommandQueue()
    sync_counter = SyncCounter()
    bridge = RealtimeBridge()
    listener = bridge._make_listener(model, od, queue, sync_counter, node_id)
    return listener, model, queue, sync_counter


def test_rpdo1_frame_queues_controlword_as_immediate():
    listener, model, queue, _sync = make_listener()
    msg = can.Message(arbitration_id=0x201, data=[0x07, 0x00], is_extended_id=False)
    listener.on_message_received(msg)
    assert queue.pending_count() == 1
    queue.drain(model)
    assert model.read_object(0x6040) == 0x0007


def test_rpdo2_frame_decodes_two_mapped_objects():
    listener, model, queue, _sync = make_listener()
    # RPDO2 既定マッピング: 6040h(16bit) + 6060h(8bit)
    msg = can.Message(arbitration_id=0x301, data=[0x0F, 0x00, 0x03], is_extended_id=False)
    listener.on_message_received(msg)
    queue.drain(model)
    assert model.read_object(0x6040) == 0x000F


def test_sync_transmission_type_rpdo_is_queued_as_sync_trigger():
    listener, model, queue, _sync = make_listener()
    model.write_object(0x1400, 2, 0x00)  # SYNC 反映へ変更
    before = model.read_object(0x6040)
    msg = can.Message(arbitration_id=0x201, data=[0x07, 0x00], is_extended_id=False)
    listener.on_message_received(msg)
    queue.drain(model, sync_received=False)
    assert model.read_object(0x6040) == before  # まだ変わらない (SYNC 待ち)
    queue.drain(model, sync_received=True)
    assert model.read_object(0x6040) == 0x0007


def test_disabled_rpdo_is_ignored():
    listener, model, queue, _sync = make_listener()
    model.write_object(0x1400, 1, model.rpdo_comm[0].cob_id | (1 << 31))  # 無効化
    msg = can.Message(arbitration_id=0x201, data=[0x07, 0x00], is_extended_id=False)
    listener.on_message_received(msg)
    assert queue.pending_count() == 0


def test_unrelated_cob_id_is_ignored():
    listener, model, queue, _sync = make_listener()
    msg = can.Message(arbitration_id=0x999, data=[0x07, 0x00], is_extended_id=False)
    listener.on_message_received(msg)
    assert queue.pending_count() == 0


def test_sync_frame_notifies_sync_counter():
    listener, _model, _queue, sync_counter = make_listener()
    msg = can.Message(arbitration_id=0x80, data=[], is_extended_id=False)
    listener.on_message_received(msg)
    assert sync_counter.take() == 1


def test_remote_frame_at_sync_cob_id_is_not_treated_as_sync():
    listener, _model, _queue, sync_counter = make_listener()
    msg = can.Message(arbitration_id=0x80, data=[], is_extended_id=False,
                      is_remote_frame=True)
    listener.on_message_received(msg)
    assert sync_counter.take() == 0
