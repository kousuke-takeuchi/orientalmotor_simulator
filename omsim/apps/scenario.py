"""YAML シナリオをマスタ役として流す最小版ランナー。"""
import argparse
import collections
import sys
import time
import xml.etree.ElementTree as ET

import canopen
import yaml

from omsim.can.bus import close_network, open_network
from omsim.node.eds import DEFAULT_EDS_PATH, find_eds

Scenario = collections.namedtuple("Scenario", ["name", "nodes", "steps"])
StepResult = collections.namedtuple("StepResult", ["index", "kind", "ok", "detail"])

STEP_KINDS = ("nmt", "sdo_write", "sdo_read", "expect", "wait", "pdo_send")
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
        node.sdo.RESPONSE_TIMEOUT = 1.0
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
    deadline = time.monotonic() + timeout
    actual = None
    while time.monotonic() < deadline:
        actual = _sdo_variable(remote, step["index"], step["sub"]).raw
        if _matches(actual, step):
            return True, "node{} actual={}".format(node_id, actual)
        time.sleep(0.01)
    return False, "node{} actual={} expected={}".format(node_id, actual, step["value"])


def run_scenario(scenario, network, timeout_default=2.0, eds=None):
    remotes = _remote_nodes(network, scenario.nodes, find_eds(eds or DEFAULT_EDS_PATH))
    results = []
    for position, step in enumerate(scenario.steps):
        kind = step["kind"]
        ok, detail = True, ""
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
                    ok, detail = _run_expect(
                        remote, node_id, step, float(step.get("timeout", timeout_default)))
                    if not ok:
                        break
                elif kind == "pdo_send":
                    network.send_message(_as_int(step["cob_id"]), bytes(step["data"]))
                else:
                    raise NotImplementedError("未対応のステップ: {}".format(kind))
        except Exception as err:  # シナリオ実行の失敗は結果として記録する
            ok, detail = False, "{}: {}".format(type(err).__name__, err)
        results.append(StepResult(index=position, kind=kind, ok=ok, detail=detail))
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
        )
        if not result.ok:
            failure = ET.SubElement(case, "failure", message=result.detail or "failed")
            failure.text = result.detail
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="omsim-scenario")
    parser.add_argument("scenario")
    parser.add_argument("--channel", default="vcan0")
    parser.add_argument("--interface", default="socketcan")
    parser.add_argument("--bitrate", type=int, default=500000)
    parser.add_argument("--eds", default=DEFAULT_EDS_PATH)
    parser.add_argument("--junit", default=None)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    scenario = load_scenario(args.scenario)
    network = open_network(args.channel, args.interface, args.bitrate)
    try:
        results = run_scenario(scenario, network, eds=args.eds)
    finally:
        close_network(network)
    if args.junit:
        write_junit(results, scenario, args.junit)
    for result in results:
        mark = "PASS" if result.ok else "FAIL"
        print("{} step{} {} {}".format(mark, result.index, result.kind, result.detail))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
