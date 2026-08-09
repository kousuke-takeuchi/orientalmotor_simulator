from omsim.node.eds import DEFAULT_EDS_PATH
from omsim.sim.manager import NodeManager, NodeSpec
from omsim.sim.recorder import Recorder
from omsim.web.hub import SnapshotHub


def make_hub(history_size=600):
    specs = [
        NodeSpec(node_id=1, eds=DEFAULT_EDS_PATH),
        NodeSpec(node_id=2, eds=DEFAULT_EDS_PATH),
    ]
    manager = NodeManager(specs, network=None, realtime=False)
    recorder = Recorder(None)
    return SnapshotHub(manager, recorder, history_size=history_size), manager, recorder


def test_latest_is_none_before_first_capture():
    hub, _manager, recorder = make_hub()
    assert hub.latest() is None
    recorder.close()


def test_capture_returns_and_stores_the_snapshot():
    hub, manager, recorder = make_hub()
    manager.step()
    snap = hub.capture()
    assert snap["nodes"][1]["node_id"] == 1
    assert hub.latest() is snap
    assert len(hub.history()) == 1
    recorder.close()


def test_history_is_bounded():
    hub, manager, recorder = make_hub(history_size=10)
    for _ in range(50):
        manager.step()
        hub.capture()
    assert len(hub.history()) == 10
    recorder.close()


def test_history_limit_returns_the_newest():
    hub, manager, recorder = make_hub()
    for _ in range(5):
        manager.step()
        hub.capture()
    recent = hub.history(limit=2)
    assert len(recent) == 2
    assert recent[-1] is hub.latest()
    recorder.close()


def test_frames_come_from_the_recorder():
    hub, manager, recorder = make_hub()
    recorder.frame("bus", 0x701, bytes([0x00]), 0.0)
    assert len(hub.frames()) == 1
    assert hub.frames()[0]["can_id"] == 0x701
    recorder.close()


def test_payload_contains_every_node_and_the_frames():
    hub, manager, recorder = make_hub()
    manager.step()
    recorder.frame("bus", 0x701, bytes([0x00]), 0.0)
    hub.capture()
    payload = hub.payload()
    assert sorted(payload["nodes"]) == [1, 2]
    assert len(payload["frames"]) == 1
    assert "sim_time" in payload
    recorder.close()


def test_payload_before_capture_is_still_valid():
    hub, _manager, recorder = make_hub()
    payload = hub.payload()
    assert payload["nodes"] == {}
    assert payload["frames"] == []
    recorder.close()
