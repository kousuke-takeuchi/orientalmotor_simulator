import pytest

from omsim.apps.omsim_main import main, parse_args, warn_ignored_mxex
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


def test_warn_ignored_mxex_warns_for_nodes_with_mxex(capsys):
    args = parse_args(["--node", "2=/tmp/left.mxex", "--node", "1"])
    warn_ignored_mxex(args.nodes)
    captured = capsys.readouterr()
    assert "left.mxex" in captured.err
    assert "P5" in captured.err
    assert "node_id=2" in captured.err
    # mxex を指定していないノード (node_id=1) については警告しない。
    assert "node_id=1" not in captured.err


def test_warn_ignored_mxex_is_silent_without_mxex(capsys):
    args = parse_args(["--node", "1", "--node", "2"])
    warn_ignored_mxex(args.nodes)
    captured = capsys.readouterr()
    assert captured.err == ""


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
    assert (0x6081, 0) in printed_keys
    assert (0x60FE, 1) in printed_keys
    assert (0x1016, 1) in printed_keys


def test_web_port_defaults_to_disabled():
    assert parse_args([]).web_port is None


def test_web_port_is_parsed():
    assert parse_args(["--web-port", "8080"]).web_port == 8080


def test_web_host_defaults_to_all_interfaces():
    assert parse_args([]).web_host == "0.0.0.0"
