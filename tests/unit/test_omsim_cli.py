import pytest

from omsim.apps.omsim_main import load_node_mxex, main, parse_args
from omsim.driver.model import DriverModel


def test_defaults_to_one_node_on_vcan0():
    args = parse_args([])
    assert args.channel == "vcan0"
    assert args.interface == "socketcan"
    assert args.bitrate == 500000
    assert [spec.node_id for spec in args.nodes] == [1]
    assert args.nodes[0].mxex is None


def test_parses_multiple_nodes():
    args = parse_args(["--node", "1", "--node", "2"])
    assert [spec.node_id for spec in args.nodes] == [1, 2]


def test_parses_node_with_mxex():
    args = parse_args(["--node", "2=/tmp/left.mxex"])
    assert args.nodes[0].node_id == 2
    assert args.nodes[0].mxex == "/tmp/left.mxex"


def test_every_node_gets_the_selected_eds():
    args = parse_args(["--eds", "BLVD-KRD_CANopen_V400.eds", "--node", "1", "--node", "2"])
    assert args.nodes[0].eds.endswith("BLVD-KRD_CANopen_V400.eds")
    assert args.nodes[1].eds == args.nodes[0].eds


def test_rejects_duplicate_node_ids():
    with pytest.raises(SystemExit):
        parse_args(["--node", "1", "--node", "1"])


def test_rejects_non_numeric_node_id():
    with pytest.raises(SystemExit):
        parse_args(["--node", "abc"])


def test_parses_list_stubs_flag():
    args = parse_args(["--list-stubs"])
    assert args.list_stubs is True


def test_list_stubs_defaults_to_false():
    args = parse_args([])
    assert args.list_stubs is False


def test_load_node_mxex_applies_and_reports(capsys, tmp_path):
    """P5 で mxex は実際に適用される。適用件数を必ず出す。"""
    import io as _io

    from omsim.driver.model import DriverModel

    path = tmp_path / "right.mxex"
    with _io.open(str(path), "w", encoding="utf-8") as out:
        out.write('﻿<?xml version="1.0"?><FileDataTree><NetIds>'
                  '<netid id="50" val="40"><att key="bank" val="1" /></netid>'
                  "</NetIds></FileDataTree>")

    class FakeManager(object):
        def __init__(self):
            self.models = {2: DriverModel(node_id=2)}

    manager = FakeManager()
    args = parse_args(["--node", "2={}".format(path), "--node", "1"])
    load_node_mxex(manager, args.nodes)
    captured = capsys.readouterr()
    assert "node_id=2" in captured.err
    assert "件を適用" in captured.err
    # mxex を指定していないノード (node_id=1) については何も出さない。
    assert "node_id=1" not in captured.err
    assert manager.models[2].read_object(0x4032) == 40


def test_load_node_mxex_is_silent_without_mxex(capsys):
    args = parse_args(["--node", "1", "--node", "2"])
    load_node_mxex(None, args.nodes)
    captured = capsys.readouterr()
    assert captured.err == ""


def test_mxex_diff_option_defaults_to_none():
    assert parse_args([]).mxex_diff is None


def test_list_stubs_prints_stub_lines_and_exits_without_opening_network(capsys):
    exit_code = main(["--list-stubs"])
    assert exit_code == 0

    captured = capsys.readouterr()
    printed_keys = set()
    for line in captured.out.splitlines():
        addr = line.split(" ", 1)[0]
        index_str, sub_str = addr.split(":")
        printed_keys.add((int(index_str, 16), int(sub_str, 16)))

    expected_keys = set(
        (index, sub) for index, sub, _reason in DriverModel.router.stubs()
    )
    assert printed_keys == expected_keys
    assert (0x409B, 0) in printed_keys
    # 6081h は pp モード実装 (P4) でスタブではなくなった
    assert (0x6081, 0) not in printed_keys
    # 60FEh:01 は P5 のリモート I/O 実装でスタブから外れた
    assert (0x60FE, 1) not in printed_keys
    # 1016h は P3 で実働になったため、スタブ一覧には出ない。
    assert (0x1016, 1) not in printed_keys


def test_web_port_defaults_to_disabled():
    assert parse_args([]).web_port is None


def test_web_port_is_parsed():
    assert parse_args(["--web-port", "8080"]).web_port == 8080


def test_web_host_defaults_to_localhost():
    assert parse_args([]).web_host == "127.0.0.1"


def test_wiring_defaults_to_standard():
    assert parse_args([]).wiring == "standard"


def test_wiring_accepts_the_pitakuru_preset():
    assert parse_args(["--wiring", "pitakuru"]).wiring == "pitakuru"


def test_wiring_rejects_an_unknown_preset():
    import pytest

    with pytest.raises(SystemExit):
        parse_args(["--wiring", "nonsense"])


def test_replay_option_defaults_to_none():
    assert parse_args([]).replay is None


def test_replay_requires_a_web_port(capsys):
    from omsim.apps.omsim_main import run_replay

    args = parse_args(["--replay", "/tmp/none.jsonl"])
    assert run_replay(args) == 2
    assert "--web-port" in capsys.readouterr().err
