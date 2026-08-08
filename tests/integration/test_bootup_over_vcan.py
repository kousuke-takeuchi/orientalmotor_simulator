"""NodeManager.start() が CiA301 4.3 の NMT boot-up メッセージを
実際に CAN バスへ送出することの結合テスト。

node.nmt.state への直接代入は canopen.NmtSlave の内部状態を書き換える
だけでフレームを一切送出しないため、このテストは修正前の実装では失敗する
（バス上のフレームが 0 件になる）。
"""
import time

import pytest

from omsim.can.bus import close_network, open_network
from omsim.node.eds import DEFAULT_EDS_PATH
from omsim.sim.clock import SimClock
from omsim.sim.manager import NodeManager, NodeSpec
from omsim.sim.recorder import Recorder, attach_recorder

pytestmark = pytest.mark.vcan


def test_start_sends_nmt_bootup_frames_for_all_nodes(vcan_available, master):
    # マスタ役の network（被試験体とは別ソケット）でバスを観測する。
    # SocketCAN は receive_own_messages が既定 False のため、被試験体自身の
    # network では自分が送信したフレームを観測できない。
    recorder = Recorder(None)
    clock = SimClock(realtime=False)
    attach_recorder(master, recorder, clock)

    network = open_network(channel=vcan_available)
    specs = [
        NodeSpec(node_id=1, eds=DEFAULT_EDS_PATH),
        NodeSpec(node_id=2, eds=DEFAULT_EDS_PATH),
    ]
    manager = NodeManager(specs, network=network, realtime=False)
    try:
        manager.start()
        time.sleep(0.3)

        frames = recorder.recent_frames()
        bootups = dict(
            (f["can_id"], f["data"]) for f in frames if f["can_id"] in (0x701, 0x702)
        )
        assert bootups.get(0x701) == "00", "node_id=1 の boot-up (0x701) が観測できない: {}".format(frames)
        assert bootups.get(0x702) == "00", "node_id=2 の boot-up (0x702) が観測できない: {}".format(frames)
    finally:
        manager.stop()
        close_network(network)
        recorder.close()
