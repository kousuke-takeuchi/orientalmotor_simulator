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
