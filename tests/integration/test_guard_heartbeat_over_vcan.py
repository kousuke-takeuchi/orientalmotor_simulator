import time

import can
import pytest

pytestmark = pytest.mark.vcan


def test_node_guard_rtr_gets_toggled_response(stepped_sim, master):
    node_id = 1
    bus = can.interface.Bus(channel="vcan0", interface="socketcan")
    try:
        request = can.Message(arbitration_id=0x700 + node_id, is_remote_frame=True,
                              is_extended_id=False, dlc=0)
        response_bytes = []
        for _ in range(2):
            bus.send(request)
            deadline = time.time() + 1.0
            got = None
            while time.time() < deadline:
                msg = bus.recv(timeout=0.1)
                if msg is None:
                    continue
                if msg.arbitration_id == 0x700 + node_id and not msg.is_remote_frame:
                    got = msg
                    break
            assert got is not None
            response_bytes.append(got.data[0])
        # 2 回とも Pre-operational (0x7F) だが toggle bit (0x80) が反転しているはず。
        assert (response_bytes[0] & 0x7F) == 0x7F
        assert (response_bytes[0] & 0x80) != (response_bytes[1] & 0x80)
    finally:
        bus.shutdown()
