"""omsim 本体の CLI。"""
import argparse
import signal
import sys

from omsim.can.bus import close_network, open_network
from omsim.driver.model import DriverModel
from omsim.node.eds import DEFAULT_EDS_PATH, find_eds
from omsim.sim.manager import NodeManager, NodeSpec
from omsim.sim.recorder import Recorder, attach_recorder
from omsim.sim.wiring import PRESETS as WIRING_PRESETS
from omsim.sim.wiring import Cn4Wiring


def format_stubs(stubs):
    lines = []
    for index, sub, reason in stubs:
        lines.append("0x{:04X}:{:02X}  {}".format(index, sub, reason))
    return lines


def load_node_mxex(manager, nodes, stream=None):
    """--node ID=MXEX で指定された mxex を各ノードへ適用する (P5)。

    適用できなかった件数は黙って捨てず必ず出す。「渡したつもりが効いて
    いない」という気付きにくい事故を防ぐため。
    """
    from omsim.apps.mxex import apply_mxex

    stream = sys.stderr if stream is None else stream
    for spec in nodes:
        if not spec.mxex:
            continue
        report = apply_mxex(manager.models[spec.node_id], spec.mxex)
        print(
            "mxex: node_id={} {} -> {} 件中 {} 件を適用 "
            "(未知 {} / 拒否 {} / MEXE02 専用 {})".format(
                spec.node_id, spec.mxex, report["total"], report["applied"],
                report["unknown"], report["rejected"], report["mexe02_only"]),
            file=stream,
        )


def run_replay(args):
    """記録した jsonl を Web で再生する。CAN も シミュレーションも動かさない。"""
    import time

    from omsim.sim.replay import load_recording
    from omsim.web.app import run_web
    from omsim.web.replay_hub import ReplayHub

    if args.web_port is None:
        print("--replay には --web-port が必要です", file=sys.stderr)
        return 2

    recording = load_recording(args.replay)
    hub = ReplayHub(recording)
    run_web(hub, host=args.web_host, port=args.web_port)
    print("omsim replay: http://{}:{}/ ({} 秒ぶん、壊れた行 {})".format(
        args.web_host, args.web_port, round(recording.duration, 3),
        recording.broken_lines))

    interval = 0.1
    deadline = None if args.duration is None else time.time() + args.duration
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(interval)
            hub.advance(interval)
    except KeyboardInterrupt:
        pass
    return 0


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
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="EDS に対する実装網羅率と未実装オブジェクト一覧を出力して終了する",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=None,
        help="指定するとブラウザ用の Web サーバをこのポートで起動する",
    )
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument(
        "--replay", default=None,
        help="--record で書いた jsonl を Web で再生する (シミュレーションは動かさない)")
    parser.add_argument(
        "--mxex-diff", nargs=2, metavar=("A", "B"), default=None,
        help="2 つの .mxex を netid 単位で比較して終了する")
    parser.add_argument(
        "--wiring", default="standard", choices=sorted(WIRING_PRESETS),
        help="CN4 の HWTO 配線 (standard: 2重系 / pitakuru: 片系 / none: ジャンパ短絡)")
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

    if args.coverage:
        from omsim.driver.coverage import coverage_report, format_report
        from omsim.node.eds import load_eds

        print(format_report(coverage_report(load_eds(args.eds), DriverModel.router)))
        return 0

    if args.mxex_diff:
        from omsim.apps.mxex import diff_mxex, format_diff

        for line in format_diff(diff_mxex(*args.mxex_diff)):
            print(line)
        return 0

    if args.replay:
        return run_replay(args)

    recorder = Recorder(args.record)
    network = open_network(args.channel, args.interface, args.bitrate)
    manager = NodeManager(
        args.nodes, network=network, realtime=True,
        wiring=Cn4Wiring.preset(args.wiring))
    load_node_mxex(manager, args.nodes)
    attach_recorder(network, recorder, manager.clock)
    manager.start()

    hub = None
    if args.web_port is not None:
        from omsim.web.app import run_web
        from omsim.web.hub import SnapshotHub

        hub = SnapshotHub(manager, recorder)
        run_web(hub, host=args.web_host, port=args.web_port)
        print("omsim web: http://{}:{}/".format(args.web_host, args.web_port))

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
            if hub is not None and manager.clock.tick_count % 20 == 0:
                hub.capture()
            if args.duration is not None and manager.clock.now >= args.duration:
                break
    finally:
        manager.stop()
        close_network(network)
        recorder.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
