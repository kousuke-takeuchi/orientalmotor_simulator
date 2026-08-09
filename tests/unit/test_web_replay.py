"""replay モードの Web API。"""
import io

import pytest
from fastapi.testclient import TestClient

from omsim.sim.replay import load_recording
from omsim.web.app import create_app
from omsim.web.replay_hub import ReplayHub

SAMPLE = (
    '{"kind": "state", "t": 0.0, "snapshot": {"sim_time": 0.0, "nodes": {"1": {"node_id": 1}}}}\n'
    '{"kind": "frame", "t": 0.1, "dir": "bus", "can_id": 1537, "data": "00", "text": "SDO"}\n'
    '{"kind": "state", "t": 1.0, "snapshot": {"sim_time": 1.0, "nodes": {"1": {"node_id": 1}}}}\n'
)


def make_client(tmp_path):
    path = tmp_path / "rec.jsonl"
    with io.open(str(path), "w", encoding="utf-8") as out:
        out.write(SAMPLE)
    hub = ReplayHub(load_recording(str(path)))
    return TestClient(create_app(hub)), hub


def test_state_endpoint_serves_the_recorded_snapshot(tmp_path):
    client, _hub = make_client(tmp_path)
    body = client.get("/api/state").json()
    assert body["sim_time"] == 0.0
    assert body["replay"]["duration"] == 1.0


def test_seeking_changes_the_served_snapshot(tmp_path):
    client, _hub = make_client(tmp_path)
    body = client.post("/api/replay", json={"position": 1.0}).json()
    assert body["position"] == 1.0
    assert client.get("/api/state").json()["sim_time"] == 1.0


def test_seek_outside_the_recording_is_clamped(tmp_path):
    client, _hub = make_client(tmp_path)
    assert client.post("/api/replay", json={"position": 99.0}).json()["position"] == 1.0
    assert client.post("/api/replay", json={"position": -5.0}).json()["position"] == 0.0


def test_playing_flag_round_trips(tmp_path):
    client, _hub = make_client(tmp_path)
    assert client.post("/api/replay", json={"playing": True}).json()["playing"] is True
    assert client.post("/api/replay", json={"playing": False}).json()["playing"] is False


def test_wiring_endpoint_is_not_available_in_replay(tmp_path):
    """再生は読み取り専用。配線やリレーは触れない。"""
    client, _hub = make_client(tmp_path)
    assert client.post("/api/wiring", json={"relay": False}).status_code == 409


def test_wiring_get_is_409_not_500_in_replay(tmp_path):
    """再生モードでは配線が無い。500 ではなく「今は無い」と返す。"""
    client, _hub = make_client(tmp_path)
    response = client.get("/api/wiring")
    assert response.status_code == 409
    assert "再生" in response.json()["detail"] or "記録" in response.json()["detail"]
