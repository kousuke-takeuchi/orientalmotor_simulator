import json
import os

from omsim.sim.recorder import Recorder


def test_writes_frames_and_state_as_jsonl(tmp_path):
    path = os.path.join(str(tmp_path), "run.jsonl")
    rec = Recorder(path)
    rec.frame("rx", 0x601, bytes([0x40, 0x41, 0x60, 0x00, 0, 0, 0, 0]), 0.001)
    rec.state({"sim_time": 0.001, "nodes": {1: {"node_id": 1}}})
    rec.close()

    lines = [json.loads(line) for line in open(path, encoding="utf-8")]
    assert lines[0]["kind"] == "frame"
    assert lines[0]["can_id"] == 0x601
    assert lines[0]["text"] == "SDO rd node1 6041h:00"
    assert lines[1]["kind"] == "state"


def test_keeps_recent_frames_in_memory_without_a_path():
    rec = Recorder(None)
    for i in range(5):
        rec.frame("tx", 0x181, bytes([i]), 0.001 * i)
    recent = rec.recent_frames(limit=3)
    assert len(recent) == 3
    assert recent[-1]["can_id"] == 0x181
    rec.close()


def test_ring_buffer_is_bounded():
    rec = Recorder(None, buffer_size=10)
    for i in range(50):
        rec.frame("tx", 0x181, bytes([1]), 0.0)
    assert len(rec.recent_frames(limit=100)) == 10
    rec.close()
