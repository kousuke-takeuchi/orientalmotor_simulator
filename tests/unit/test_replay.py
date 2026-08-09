"""記録した jsonl の読み戻しと再生。"""
import io

import pytest

from omsim.sim.replay import Recording, load_recording

SAMPLE = (
    '{"kind": "state", "t": 0.0, "snapshot": {"sim_time": 0.0, "nodes": {"1": {"node_id": 1}}}}\n'
    '{"kind": "frame", "t": 0.1, "dir": "bus", "can_id": 1537, "data": "00", "text": "SDO"}\n'
    'これは壊れた行\n'
    '{"kind": "state", "t": 0.2, "snapshot": {"sim_time": 0.2, "nodes": {"1": {"node_id": 1}}}}\n'
    '{"kind": "frame", "t": 0.3, "dir": "tx", "can_id": 385, "data": "01", "text": "TPDO1"}\n'
)


def write(tmp_path, text=SAMPLE):
    path = tmp_path / "rec.jsonl"
    with io.open(str(path), "w", encoding="utf-8") as out:
        out.write(text)
    return str(path)


def test_loads_states_and_frames(tmp_path):
    recording = load_recording(write(tmp_path))
    assert len(recording.states) == 2
    assert len(recording.frames) == 2


def test_broken_lines_are_counted_not_hidden(tmp_path):
    recording = load_recording(write(tmp_path))
    assert recording.broken_lines == 1


def test_duration_comes_from_the_last_timestamp(tmp_path):
    recording = load_recording(write(tmp_path))
    assert recording.duration == 0.3


def test_payload_at_returns_the_state_at_or_before_the_time(tmp_path):
    recording = load_recording(write(tmp_path))
    payload = recording.payload_at(0.15)
    assert payload["sim_time"] == 0.0
    payload = recording.payload_at(0.25)
    assert payload["sim_time"] == 0.2


def test_payload_includes_the_frames_up_to_that_time(tmp_path):
    recording = load_recording(write(tmp_path))
    payload = recording.payload_at(0.25)
    assert [frame["can_id"] for frame in payload["frames"]] == [1537]
    payload = recording.payload_at(0.35)
    assert [frame["can_id"] for frame in payload["frames"]] == [1537, 385]


def test_empty_recording_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_recording(write(tmp_path, text="壊れた行だけ\n"))


def test_recording_without_states_is_rejected(tmp_path):
    """フレームだけの記録では再生できない。黙って空を返さない。"""
    only_frames = '{"kind": "frame", "t": 0.1, "can_id": 1, "data": "00", "text": "x"}\n'
    with pytest.raises(ValueError):
        load_recording(write(tmp_path, text=only_frames))


def test_recording_is_read_only():
    """再生は読み取り専用 (シミュレーションを進める口を持たない)。"""
    assert not hasattr(Recording, "step")
