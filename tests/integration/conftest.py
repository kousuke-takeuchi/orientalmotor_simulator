import subprocess
import threading

import can
import pytest

from omsim.can.bus import close_network, open_network
from omsim.node.eds import DEFAULT_EDS_PATH
from omsim.sim.manager import NodeManager, NodeSpec

VCAN = "vcan0"

# バス排他チェック（プリフライト）専用のタイムアウト。応答が無いのが
# 正常系のため、ここで長く待つとテスト起動そのものが遅くなる。
_PREFLIGHT_TIMEOUT = 0.3


def _vcan_is_up():
    try:
        out = subprocess.check_output(["ip", "-o", "link", "show", VCAN])
    except (OSError, subprocess.CalledProcessError):
        return False
    return b"state UP" in out or b"UNKNOWN" in out


def _sdo_responder_present(channel, node_id, timeout=_PREFLIGHT_TIMEOUT):
    """node_id の SDO サーバ (1008h upload) に応答する何者かが既に居るか確認する。

    バス上に omsim の残骸プロセスが残っていると、これから起動する
    シミュレータのノードと合わせて同じ node_id の SDO サーバが 2 つ生き、
    マスタから見た応答ストリームが 1 フレームずれる（1008h の segmented
    転送でのみ症状が出る flaky の根本原因）。テストがそれを踏んでから
    気づくのではなく、シミュレータを起動する前に検出して即座に落とす。
    """
    bus = can.interface.Bus(
        channel=channel,
        interface="socketcan",
        can_filters=[{"can_id": 0x580 + node_id, "can_mask": 0x7FF}],
        receive_own_messages=False,
    )
    try:
        # SDO initiate upload request (1008h:00)。応答者が居れば
        # 0x580+node_id から何か返ってくる。
        request = can.Message(
            arbitration_id=0x600 + node_id,
            data=[0x40, 0x08, 0x10, 0x00, 0, 0, 0, 0],
            is_extended_id=False,
        )
        bus.send(request)
        return bus.recv(timeout=timeout) is not None
    finally:
        bus.shutdown()


@pytest.fixture(scope="session")
def vcan_available():
    if not _vcan_is_up():
        pytest.skip("{} が無いので skip。scripts/setup_vcan.sh を実行してください".format(VCAN))
    for node_id in (1, 2):
        if _sdo_responder_present(VCAN, node_id):
            pytest.fail(
                "{} に既にノード {} の応答者がいます。omsim プロセスが残っていないか"
                "確認してください（`pgrep -af omsim.apps` で確認し kill する）。"
                "同じ node_id のノードがバス上に 2 つ存在すると SDO 応答が二重に返り、"
                "マスタの応答ストリームが 1 フレームずれて後続のテストが原因不明の"
                "Unexpected response で flaky に落ちます。".format(VCAN, node_id)
            )
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
    if thread.is_alive():
        manager.stop()
        close_network(network)
        pytest.fail("シミュレータのスレッドが 2 秒以内に停止しませんでした")
    manager.stop()
    close_network(network)


@pytest.fixture
def stepped_sim(vcan_available):
    """テスト側が明示的に step を進めるシミュレータ（スレッドを使わない）。"""
    network = open_network(channel=vcan_available)
    specs = [
        NodeSpec(node_id=1, eds=DEFAULT_EDS_PATH),
        NodeSpec(node_id=2, eds=DEFAULT_EDS_PATH),
    ]
    manager = NodeManager(specs, network=network, realtime=False)
    manager.start()
    yield manager
    manager.stop()
    close_network(network)


@pytest.fixture
def master(vcan_available):
    """被試験体と同じ立場のマスタ。"""
    network = open_network(channel=vcan_available)
    yield network
    close_network(network)
