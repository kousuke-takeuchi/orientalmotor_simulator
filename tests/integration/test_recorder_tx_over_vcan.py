"""自ノードの送信フレームが CAN ログに tx として載ることを実バス上で確認する。

SocketCAN は receive_own_messages が既定 False のため、受信専用の
FrameListener には自分の送信が返ってこない。ここは vcan0 上の実物で
確認する必要がある (FakeNetwork では送信経路そのものが無い)。
"""
import time

import pytest

from omsim.can.bus import close_network, open_network
from omsim.sim.clock import SimClock
from omsim.sim.recorder import Recorder, attach_recorder


@pytest.mark.vcan
def test_own_transmitted_frames_are_recorded_as_tx(vcan_available):
    recorder = Recorder(None)
    clock = SimClock(realtime=False)
    network = open_network(channel=vcan_available)
    attach_recorder(network, recorder, clock)
    try:
        # NMT boot-up と同じ経路 (network.send_message) で 1 フレーム送る。
        network.send_message(0x701, [0])
        time.sleep(0.1)
        tx_frames = [f for f in recorder.recent_frames() if f["dir"] == "tx"]
        assert any(f["can_id"] == 0x701 and f["data"] == "00" for f in tx_frames)
    finally:
        close_network(network)
        recorder.close()
