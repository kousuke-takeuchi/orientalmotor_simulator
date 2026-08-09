import json

from fastapi.testclient import TestClient

from omsim.node.eds import DEFAULT_EDS_PATH
from omsim.sim.manager import NodeManager, NodeSpec
from omsim.sim.recorder import Recorder
from omsim.web.app import create_app
from omsim.web.hub import SnapshotHub


def make_client():
    specs = [
        NodeSpec(node_id=1, eds=DEFAULT_EDS_PATH),
        NodeSpec(node_id=2, eds=DEFAULT_EDS_PATH),
    ]
    manager = NodeManager(specs, network=None, realtime=False)
    recorder = Recorder(None)
    hub = SnapshotHub(manager, recorder)
    manager.step()
    hub.capture()
    return TestClient(create_app(hub)), manager, recorder


def test_state_endpoint_returns_every_node():
    client, _manager, recorder = make_client()
    body = client.get("/api/state").json()
    assert sorted(body["nodes"]) == ["1", "2"]
    assert "sim_time" in body
    recorder.close()


def test_state_endpoint_includes_frames():
    client, _manager, recorder = make_client()
    body = client.get("/api/state").json()
    assert isinstance(body["frames"], list)
    recorder.close()


def test_stubs_endpoint_lists_unimplemented_objects():
    client, _manager, recorder = make_client()
    body = client.get("/api/stubs").json()
    assert len(body["stubs"]) > 0
    entry = body["stubs"][0]
    assert set(entry) == {"index", "sub", "reason"}
    recorder.close()


def test_root_serves_the_page():
    client, _manager, recorder = make_client()
    response = client.get("/")
    assert response.status_code == 200
    assert "omsim" in response.text.lower()
    recorder.close()


def test_websocket_sends_a_payload_on_connect():
    client, _manager, recorder = make_client()
    with client.websocket_connect("/ws") as socket:
        payload = json.loads(socket.receive_text())
    assert sorted(payload["nodes"]) == ["1", "2"]
    recorder.close()
