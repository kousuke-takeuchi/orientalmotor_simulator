"""通信途絶での自動停止を実バス上で確認する。

マスタ役が Heartbeat を送っている間は回り続け、送信を止めると 0.5 秒で
無励磁 (HWTO 相当の停止) になることを vcan0 上で実測する。
"""
import time

import pytest

pytestmark = pytest.mark.vcan

MASTER_NODE_ID = 0x7F
TIMEOUT_MS = 500


def _send_heartbeat(master):
    # Heartbeat は COB-ID 700h+NodeID、データ 1 バイト (NMT 状態: 5 = Operational)
    master.send_message(0x700 + MASTER_NODE_ID, bytes([5]))


def test_motor_stops_when_the_master_stops_talking(stepped_sim, master):
    node_id = 1
    model = stepped_sim.models[node_id]

    model.write_object(0x6060, 0, 3)
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        stepped_sim.step()
    model.write_object(0x60FF, 0, 200)
    # Heartbeat consumer を設定 (マスタ node 7Fh を 500ms 監視)
    model.write_object(0x1016, 1, (MASTER_NODE_ID << 16) | TIMEOUT_MS)

    # 通信できている間は回り続ける
    for tick in range(1500):
        if tick % 100 == 0:
            _send_heartbeat(master)
            time.sleep(0.005)
        stepped_sim.step()
    assert abs(model.actual_velocity_rpm - 200) < 5
    assert model.plant.excited is True

    # マスタが黙る
    for _ in range(1500):
        stepped_sim.step()
    assert abs(model.actual_velocity_rpm) < 2
    assert model.plant.excited is False
    assert model.brake_engaged is True
    assert model.alarms.is_active
