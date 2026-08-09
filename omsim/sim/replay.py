"""記録した jsonl を読み戻して再生する (読み取り専用)。

`Recorder` が書いた `{"kind": "state", ...}` と `{"kind": "frame", ...}` を
読み、任意の時刻の Web ペイロード (`/api/state` と同じ形) を作る。

シミュレーションは一切動かさない。再生中に SDO を受けたりしないよう、
進める口 (step) をあえて持たせていない。
"""
import bisect
import io
import json


class Recording(object):
    def __init__(self, states, frames, broken_lines=0):
        self.states = states          # [(t, snapshot), ...] 時刻順
        self.frames = frames          # [(t, frame), ...] 時刻順
        self.broken_lines = broken_lines
        self._state_times = [t for t, _ in states]
        self._frame_times = [t for t, _ in frames]

    @property
    def duration(self):
        last = 0.0
        if self._state_times:
            last = max(last, self._state_times[-1])
        if self._frame_times:
            last = max(last, self._frame_times[-1])
        return last

    def payload_at(self, seconds, frame_limit=50):
        """その時刻の Web ペイロードを作る (/api/state と同じ形)。"""
        position = bisect.bisect_right(self._state_times, seconds) - 1
        if position < 0:
            position = 0
        snapshot = self.states[position][1]
        upto = bisect.bisect_right(self._frame_times, seconds)
        frames = [frame for _t, frame in self.frames[max(0, upto - frame_limit):upto]]
        return {
            "sim_time": snapshot.get("sim_time", self.states[position][0]),
            "nodes": snapshot.get("nodes", {}),
            "frames": frames,
            "replay": {"position": seconds, "duration": self.duration},
        }


def load_recording(path):
    """jsonl を読み込む。壊れた行は数える (黙って捨てない)。"""
    states, frames, broken = [], [], 0
    with io.open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                broken += 1
                continue
            kind = record.get("kind")
            if kind == "state":
                states.append((float(record.get("t", 0.0)), record.get("snapshot", {})))
            elif kind == "frame":
                frames.append((float(record.get("t", 0.0)), record))
            else:
                broken += 1
    if not states and not frames:
        raise ValueError(
            "{} に読める記録がありません (壊れた行 {} 行)".format(path, broken))
    if not states:
        raise ValueError(
            "{} には状態スナップショットがありません。フレームだけでは再生できません "
            "(omsim を --record 付きで起動してください)".format(path))
    states.sort(key=lambda item: item[0])
    frames.sort(key=lambda item: item[0])
    return Recording(states, frames, broken_lines=broken)
