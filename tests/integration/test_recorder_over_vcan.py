import subprocess
import time

import pytest

from omsim.can.bus import close_network, open_network
from omsim.sim.clock import SimClock
from omsim.sim.recorder import Recorder, attach_recorder

pytestmark = pytest.mark.vcan


def test_recorder_captures_a_real_frame_over_vcan(vcan_available):
    network = open_network(channel=vcan_available)
    recorder = Recorder(None)
    clock = SimClock(realtime=False)
    attach_recorder(network, recorder, clock)
    try:
        # network.send_message() は python-can の receive_own_messages が
        # 既定で False のため自プロセス自身のソケットには戻ってこない。
        # 実機と同じく別プロセス（cansend）から流し、SocketCAN 経由で
        # 受信側の Notifier が本当に呼ばれることを確認する。
        subprocess.check_call(["cansend", vcan_available, "000#0101"])
        time.sleep(0.2)
        frames = recorder.recent_frames()
        assert len(frames) >= 1
        assert frames[0]["can_id"] == 0x000
        assert frames[0]["text"]
    finally:
        close_network(network)
        recorder.close()
