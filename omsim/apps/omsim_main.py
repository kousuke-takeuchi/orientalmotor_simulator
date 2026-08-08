"""omsim 本体の CLI。"""
import argparse
import signal
import sys

from omsim.can.bus import close_network, open_network
from omsim.driver.model import DriverModel
from omsim.node.eds import DEFAULT_EDS_PATH, find_eds
from omsim.sim.manager import NodeManager, NodeSpec
from omsim.sim.recorder import Recorder, attach_recorder


def format_stubs(stubs):
    lines = []
    for index, sub, reason in stubs:
        lines.append("0x{:04X}:{:02X}  {}".format(index, sub, reason))
    return lines


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="omsim", description="BLVD-KRD CANopen シミュレータ")
    parser.add_argument("--channel", default="vcan0")
    parser.add_argument("--interface", default="socketcan")
    parser.add_argument("--bitrate", type=int, default=500000)
    parser.add_argument("--eds", default=DEFAULT_EDS_PATH)
    parser.add_argument(
        "--node",
        action="append",
        dest="node_specs",
        metavar="ID[=MXEX]",
        help="ノードを追加する。複数指定可。例: --node 1 --node 2=left.mxex",
    )
    parser.add_argument("--record", default=None, help="jsonl の記録先")
    parser.add_argument("--duration", type=float, default=None, help="指定秒で終了（テスト用）")
    parser.add_argument(
        "--list-stubs", action="store_true",
        help="未実装（スタブ）オブジェクトの一覧を出力して終了する",
    )
    args = parser.parse_args(argv)

    eds_path = find_eds(args.eds)
    raw_specs = args.node_specs or ["1"]
    nodes = []
    seen = set()
    for item in raw_specs:
        if "=" in item:
            id_part, mxex = item.split("=", 1)
        else:
            id_part, mxex = item, None
        if not id_part.strip().isdigit():
            parser.error("--node の ID が数値ではありません: {}".format(item))
        node_id = int(id_part)
        if node_id in seen:
            parser.error("--node の ID が重複しています: {}".format(node_id))
        seen.add(node_id)
        nodes.append(NodeSpec(node_id=node_id, eds=eds_path, mxex=mxex))
    args.nodes = nodes
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.list_stubs:
        for line in format_stubs(DriverModel.router.stubs()):
            print(line)
        return 0

    recorder = Recorder(args.record)
    network = open_network(args.channel, args.interface, args.bitrate)
    manager = NodeManager(args.nodes, network=network, realtime=True)
    attach_recorder(network, recorder, manager.clock)
    manager.start()

    stopping = {"flag": False}

    def on_signal(signum, frame):
        stopping["flag"] = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    print("omsim: {} on {} nodes={}".format(
        args.interface, args.channel, sorted(manager.models)))
    try:
        while not stopping["flag"]:
            manager.step()
            if manager.clock.tick_count % 100 == 0:
                recorder.state(manager.snapshot())
            if args.duration is not None and manager.clock.now >= args.duration:
                break
    finally:
        manager.stop()
        close_network(network)
        recorder.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
