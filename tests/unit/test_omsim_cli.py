import pytest

from omsim.apps.omsim_main import parse_args


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
