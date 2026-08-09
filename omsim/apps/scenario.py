"""YAML シナリオをマスタ役として流す最小版ランナー。"""
import argparse
import collections
import contextlib
import io
import json
import os
import sys
import urllib.request
import time
import xml.etree.ElementTree as ET

from xml.sax.saxutils import escape

import canopen
import yaml

from omsim.can.bus import close_network, open_network
from omsim.node.eds import DEFAULT_EDS_PATH, find_eds

Scenario = collections.namedtuple("Scenario", ["name", "nodes", "steps"])
StepResult = collections.namedtuple(
    "StepResult", ["index", "kind", "ok", "detail", "seconds", "actual"])
# 所要時間と実測値は後から足したので、古い呼び出し (4 引数) も通るようにする。
StepResult.__new__.__defaults__ = (0.0, None)

STEP_KINDS = ("nmt", "sdo_write", "sdo_read", "expect", "wait", "pdo_send", "relay")

# SDO ラウンドトリップのタイムアウト。CPU 競合下では無負荷 median 2.1ms に
# 対し median 61.7ms / p90 862ms / max 2.79s まで伸びることが実測されて
# おり、1.0 秒では CPU 競合下の CI 環境で flaky になる。以前はここと
# tests/integration/test_sdo_over_vcan.py にリテラル 1.0 が二重に書かれて
# いたのを、ここ 1 箇所に集約する（結合テスト側はこの定数を import する）。
SDO_RESPONSE_TIMEOUT = 3.0

NMT_COMMANDS = {
    "start": 0x01,
    "stop": 0x02,
    "pre-operational": 0x80,
    "reset": 0x81,
    "reset-comm": 0x82,
}


def _as_int(value):
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return value
    return value


def load_scenario(path):
    with open(path, encoding="utf-8") as handle:
        doc = yaml.safe_load(handle)
    nodes = [int(n) for n in doc.get("nodes", [1])]
    steps = []
    for raw in doc["steps"]:
        kind = next(k for k in raw if k in STEP_KINDS)
        body = raw[kind]
        step = {"kind": kind}
        if isinstance(body, dict):
            step.update(body)
        else:
            step["value"] = body
        for key in ("index", "sub", "value", "mask"):
            if key in step:
                step[key] = _as_int(step[key])
        step.setdefault("sub", 0)
        step["nodes"] = [int(step.pop("node"))] if "node" in step else list(nodes)
        steps.append(step)
    return Scenario(name=doc["name"], nodes=nodes, steps=steps)


def _remote_nodes(network, node_ids, eds):
    remotes = {}
    for node_id in node_ids:
        node = canopen.RemoteNode(node_id, eds)
        network.add_node(node)
        node.sdo.RESPONSE_TIMEOUT = SDO_RESPONSE_TIMEOUT
        remotes[node_id] = node
    return remotes


def _matches(actual, step):
    if "mask" in step:
        return (actual & step["mask"]) == step["value"]
    tolerance = step.get("tolerance", 0)
    return abs(actual - step["value"]) <= tolerance


def _sdo_variable(remote, index, sub):
    """符号・長さ・型を EDS のデータ型定義に従って canopen に任せる SDO 変数を返す。

    サブインデックスを持たない単純変数（ODVariable）かつ sub=0 のときは
    remote.sdo[index] を、それ以外（Record/Array やサブインデックス指定時）は
    remote.sdo[index][sub] を返す。返り値の `.raw` で読み書きできる。
    """
    if sub == 0 and isinstance(remote.object_dictionary[index], canopen.objectdictionary.ODVariable):
        return remote.sdo[index]
    return remote.sdo[index][sub]


def _run_expect(remote, node_id, step, timeout):
    """(ok, detail, actual) を返す。actual はレポートに実測値を残すため。"""
    deadline = time.monotonic() + timeout
    actual = None
    while time.monotonic() < deadline:
        actual = _sdo_variable(remote, step["index"], step["sub"]).raw
        if _matches(actual, step):
            return True, "node{} actual={}".format(node_id, actual), actual
        time.sleep(0.01)
    return (False,
            "node{} actual={} expected={}".format(node_id, actual, step["value"]),
            actual)


def set_relay(web_url, energized):
    """omsim の Web API を叩いて安全リレーを操作する。

    リレーは omsim プロセス内部の状態で、CAN 上には現れない。シナリオは
    別プロセスのマスタ役なので、操作するには Web API を通すしかない。
    --web-url を指定していないシナリオで relay ステップを使ったら、
    黙って無視せずエラーにする。
    """
    if not web_url:
        raise RuntimeError(
            "relay ステップには --web-url が必要です "
            "(omsim 側も --web-port を付けて起動してください)")
    payload = json.dumps({"relay": bool(energized)}).encode("utf-8")
    request = urllib.request.Request(
        web_url.rstrip("/") + "/api/wiring", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with contextlib.closing(urllib.request.urlopen(request, timeout=2.0)) as response:
        return json.loads(response.read().decode("utf-8"))


def run_scenario(scenario, network, timeout_default=2.0, eds=None, web_url=None):
    remotes = _remote_nodes(network, scenario.nodes, find_eds(eds or DEFAULT_EDS_PATH))
    results = []
    for position, step in enumerate(scenario.steps):
        kind = step["kind"]
        ok, detail, actual = True, "", None
        started = time.monotonic()
        try:
            for node_id in step["nodes"]:
                remote = remotes[node_id]
                if kind == "nmt":
                    code = NMT_COMMANDS[step["value"]]
                    network.send_message(0x000, bytes([code, node_id]))
                elif kind == "wait":
                    time.sleep(float(step.get("seconds", 0.0)))
                    break
                elif kind == "sdo_write":
                    _sdo_variable(remote, step["index"], step["sub"]).raw = step["value"]
                elif kind == "sdo_read":
                    _sdo_variable(remote, step["index"], step["sub"]).raw
                elif kind == "expect":
                    ok, detail, actual = _run_expect(
                        remote, node_id, step, float(step.get("timeout", timeout_default)))
                    if not ok:
                        break
                elif kind == "relay":
                    set_relay(web_url, step["value"])
                    break
                elif kind == "pdo_send":
                    network.send_message(_as_int(step["cob_id"]), bytes(step["data"]))
                else:
                    raise NotImplementedError("未対応のステップ: {}".format(kind))
        except Exception as err:  # シナリオ実行の失敗は結果として記録する
            ok, detail = False, "{}: {}".format(type(err).__name__, err)
        results.append(StepResult(
            index=position, kind=kind, ok=ok, detail=detail,
            seconds=round(time.monotonic() - started, 3), actual=actual))
    return results


def write_junit(results, scenario, path):
    failures = sum(0 if r.ok else 1 for r in results)
    suite = ET.Element(
        "testsuite",
        name=scenario.name,
        tests=str(len(results)),
        failures=str(failures),
        errors="0",
    )
    for result in results:
        case = ET.SubElement(
            suite, "testcase",
            classname=scenario.name,
            name="step{}-{}".format(result.index, result.kind),
            time=str(result.seconds),
        )
        if not result.ok:
            failure = ET.SubElement(case, "failure", message=result.detail or "failed")
            failure.text = result.detail
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


REPORT_STYLE = """
body { font-family: sans-serif; background: #11151c; color: #dfe6ef; margin: 24px; }
h1 { font-size: 20px; }
table { border-collapse: collapse; width: 100%; margin-top: 12px; }
th, td { border: 1px solid #2b3038; padding: 6px 10px; text-align: left; font-size: 14px; }
th { background: #1a1f27; }
tr.pass td.result { color: #7ee2a8; font-weight: 600; }
tr.fail td.result { color: #ff9c9c; font-weight: 600; }
tr.fail { background: #21161a; }
pre { background: #0d1117; padding: 8px; overflow-x: auto; font-size: 12px; }
.summary { margin-top: 8px; font-size: 15px; }
.note { color: #aab3c0; font-size: 13px; }
"""


def _load_recorded_frames(record_path):
    """記録 jsonl からフレームだけを読む。壊れた行は数えて返す。"""
    frames, broken = [], 0
    if not record_path or not os.path.exists(record_path):
        return frames, broken
    with io.open(record_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                broken += 1
                continue
            if record.get("kind") == "frame":
                frames.append(record)
    return frames, broken


def write_report(results, scenario, path, record_path=None, frame_limit=20):
    """人が読むレポートを 1 枚の HTML で書く。

    外部を一切参照しない (オフラインでも、CI の成果物としても開ける)。
    失敗したステップには CAN ログの末尾を添える。記録が無ければ
    「無い」と書く (あるように見せない)。
    """
    frames, broken = _load_recorded_frames(record_path)
    passed = sum(1 for r in results if r.ok)
    failed = len(results) - passed
    total_seconds = round(sum(r.seconds for r in results), 3)

    rows = []
    for result in results:
        rows.append(
            "<tr class=\"{cls}\"><td>{index}</td><td>{kind}</td>"
            "<td class=\"result\">{result}</td><td>{seconds}</td>"
            "<td>{actual}</td><td>{detail}</td></tr>".format(
                cls="pass" if result.ok else "fail",
                index=result.index,
                kind=escape(str(result.kind)),
                result="PASS" if result.ok else "FAIL",
                seconds=result.seconds,
                actual=escape("" if result.actual is None else str(result.actual)),
                detail=escape(result.detail or ""),
            ))

    if frames:
        tail = frames[-frame_limit:]
        log_lines = "\n".join(
            "{:.3f}  {:03X}  {}".format(
                frame.get("t", 0.0), frame.get("can_id", 0), frame.get("text", ""))
            for frame in tail)
        can_section = (
            "<h2>CAN ログ (末尾 {} 件)</h2><pre>{}</pre>".format(
                len(tail), escape(log_lines)))
        if broken:
            can_section += (
                "<p class=\"note\">読めなかった行が {} 行あります。</p>".format(broken))
    else:
        can_section = (
            "<p class=\"note\">CAN ログの記録はありません "
            "(omsim を --record 付きで起動し、--record-path で渡してください)。</p>")

    html = (
        "<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\">"
        "<title>omsim シナリオ結果: {name}</title><style>{style}</style></head><body>"
        "<h1>omsim シナリオ結果: {name}</h1>"
        "<p class=\"summary\">{passed} passed / {failed} failed / 合計 {seconds} 秒</p>"
        "<table><tr><th>#</th><th>種別</th><th>結果</th><th>秒</th>"
        "<th>実測値</th><th>詳細</th></tr>{rows}</table>"
        "{can}</body></html>"
    ).format(
        name=escape(scenario.name), style=REPORT_STYLE, passed=passed, failed=failed,
        seconds=total_seconds, rows="".join(rows), can=can_section)

    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(html)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(prog="omsim-scenario")
    parser.add_argument("scenario")
    parser.add_argument("--channel", default="vcan0")
    parser.add_argument("--interface", default="socketcan")
    parser.add_argument("--bitrate", type=int, default=500000)
    parser.add_argument("--eds", default=DEFAULT_EDS_PATH)
    parser.add_argument("--junit", default=None)
    parser.add_argument("--report", default=None, help="人が読む report.html の出力先")
    parser.add_argument(
        "--record-path", default=None,
        help="omsim が --record で書いた jsonl。失敗時の CAN ログをレポートに載せる")
    parser.add_argument(
        "--web-url", default=None,
        help="omsim の Web API の URL (relay ステップに必要。例 http://127.0.0.1:8080)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    scenario = load_scenario(args.scenario)
    network = open_network(args.channel, args.interface, args.bitrate)
    try:
        results = run_scenario(scenario, network, eds=args.eds, web_url=args.web_url)
    finally:
        close_network(network)
    if args.junit:
        write_junit(results, scenario, args.junit)
    if args.report:
        write_report(results, scenario, args.report, record_path=args.record_path)
    for result in results:
        mark = "PASS" if result.ok else "FAIL"
        print("{} step{} {} {}".format(mark, result.index, result.kind, result.detail))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
