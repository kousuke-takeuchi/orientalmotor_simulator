"""修正1: inject_alarm() が実際に EMCY フレームとしてバスへ出ることの結合テスト。

NodeManager.step() が AlarmModel.pop_pending_emcy() を drain して
canopen の EMCY producer で送信しない限り、このテストは失敗する
（COB-ID 0x081 にフレームが 0 件のまま）。
"""
import time

import pytest

from omsim.sim.recorder import Recorder, attach_recorder

pytestmark = pytest.mark.vcan


def test_alarm_injection_sends_emcy_frame_observed_from_a_separate_network(
    stepped_sim, master
):
    # 被試験体 (stepped_sim) とは別の Network (master) で観測する。
    # SocketCAN は receive_own_messages が既定 False のため、被試験体自身の
    # network では自分が送信したフレームを観測できない。
    recorder = Recorder(None)
    attach_recorder(master, recorder, stepped_sim.clock)

    one = stepped_sim.models[1]
    one.inject_alarm(0x30, 0x2310, error_register=0x21)
    stepped_sim.run_for(0.5)
    time.sleep(0.3)

    frames = [f for f in recorder.recent_frames() if f["can_id"] == 0x081]
    assert frames, "node_id=1 の EMCY フレーム (0x081) が観測できない"

    data = bytes.fromhex(frames[0]["data"])
    assert len(data) == 8
    emcy_code = data[0] | (data[1] << 8)
    error_register = data[2]
    assert emcy_code == 0x2310
    assert error_register == 0x21


def test_alarm_reset_sends_error_reset_emcy_frame(stepped_sim, master):
    recorder = Recorder(None)
    attach_recorder(master, recorder, stepped_sim.clock)

    one = stepped_sim.models[1]
    one.inject_alarm(0x30, 0x2310, error_register=0x21)
    stepped_sim.run_for(0.1)
    one.clear_alarm_cause()
    one.write_object(0x40C0, 0, 1)
    stepped_sim.run_for(0.5)
    time.sleep(0.3)

    frames = [f for f in recorder.recent_frames() if f["can_id"] == 0x081]
    assert len(frames) >= 2, "アラーム発生と解除で 2 つの EMCY フレームが出るはず"

    data = bytes.fromhex(frames[-1]["data"])
    emcy_code = data[0] | (data[1] << 8)
    assert emcy_code == 0x0000, "解除時は error code 0x0000 (No error) の EMCY が出る"
