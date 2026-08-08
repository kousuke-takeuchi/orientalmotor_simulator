import subprocess
import threading

import pytest

from omsim.can.bus import close_network, open_network
from omsim.node.eds import DEFAULT_EDS_PATH
from omsim.sim.manager import NodeManager, NodeSpec

VCAN = "vcan0"


def _vcan_is_up():
    try:
        out = subprocess.check_output(["ip", "-o", "link", "show", VCAN])
    except (OSError, subprocess.CalledProcessError):
        return False
    return b"state UP" in out or b"UNKNOWN" in out


@pytest.fixture(scope="session")
def vcan_available():
    if not _vcan_is_up():
        pytest.skip("{} が無いので skip。scripts/setup_vcan.sh を実行してください".format(VCAN))
    return VCAN


@pytest.fixture
def running_sim(vcan_available):
    """node_id 1,2 のシミュレータを別スレッドで走らせる。"""
    network = open_network(channel=vcan_available)
    specs = [
        NodeSpec(node_id=1, eds=DEFAULT_EDS_PATH),
        NodeSpec(node_id=2, eds=DEFAULT_EDS_PATH),
    ]
    manager = NodeManager(specs, network=network, realtime=True)
    manager.start()
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            manager.step()

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    yield manager
    stop.set()
    thread.join(timeout=2.0)
    manager.stop()
    close_network(network)


@pytest.fixture
def master(vcan_available):
    """被試験体と同じ立場のマスタ。"""
    network = open_network(channel=vcan_available)
    yield network
    close_network(network)
