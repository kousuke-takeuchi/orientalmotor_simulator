import time

import pytest

pytestmark = pytest.mark.vcan


def test_rpdo1_over_vcan_moves_the_state_machine(stepped_sim, master):
    """マスタ役から RPDO1 (COB-ID 0x201) へ Controlword を送ると、
    キュー経由で次の step() に反映されることを実バス経由で確認する。"""
    node_id = 1
    cob_id = 0x200 + node_id
    master.send_message(cob_id, bytes([0x06, 0x00]))  # shutdown
    time.sleep(0.05)
    stepped_sim.step()
    assert stepped_sim.models[node_id].read_object(0x6040) == 0x0006


def test_tpdo1_over_vcan_reflects_statusword_after_change(stepped_sim, master):
    """TPDO1 (COB-ID 0x181) が Statusword の変化を実バス経由で送信することを確認する。"""
    import can

    node_id = 1
    bus = can.interface.Bus(channel="vcan0", interface="socketcan",
                            can_filters=[{"can_id": 0x180 + node_id, "can_mask": 0x7FF}])
    try:
        master.send_message(0x200 + node_id, bytes([0x06, 0x00]))  # RPDO1 で shutdown
        time.sleep(0.05)
        stepped_sim.step()  # queue drain + on_sync/step は step() 内で呼ばれる
        master.send_message(0x80, bytes())  # SYNC
        time.sleep(0.05)
        stepped_sim.step()
        msg = bus.recv(timeout=1.0)
        assert msg is not None
        assert msg.arbitration_id == 0x180 + node_id
    finally:
        bus.shutdown()


def test_sync_producer_transmits_periodically(stepped_sim, master):
    import can

    node_id = 1
    model = stepped_sim.models[node_id]
    model.write_object(0x1005, 0, 0x80 | (1 << 30))
    model.write_object(0x1006, 0, 5000)  # 5ms 周期

    bus = can.interface.Bus(channel="vcan0", interface="socketcan",
                            can_filters=[{"can_id": 0x80, "can_mask": 0x7FF}])
    try:
        for _ in range(20):
            stepped_sim.step()
        msg = bus.recv(timeout=1.0)
        assert msg is not None
        assert msg.arbitration_id == 0x80
    finally:
        bus.shutdown()
