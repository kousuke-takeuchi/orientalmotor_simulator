import os

from omsim.apps.scenario import load_scenario

SCENARIO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scenarios",
    "sdo_smoke.yaml",
)


def test_parses_name_and_nodes():
    scenario = load_scenario(SCENARIO)
    assert scenario.name.startswith("SDO で")
    assert scenario.nodes == [1, 2]


def test_parses_every_step_in_order():
    scenario = load_scenario(SCENARIO)
    assert [step["kind"] for step in scenario.steps] == [
        "nmt",
        "sdo_read",
        "expect",
        "wait",
        "expect",
    ]


def test_step_without_node_targets_all_nodes():
    scenario = load_scenario(SCENARIO)
    expect_all = scenario.steps[2]
    assert expect_all["nodes"] == [1, 2]


def test_step_with_explicit_node_targets_only_that_node():
    scenario = load_scenario(SCENARIO)
    assert scenario.steps[4]["nodes"] == [2]


def test_hex_indices_are_parsed_as_integers():
    scenario = load_scenario(SCENARIO)
    assert scenario.steps[1]["index"] == 0x1008
    assert scenario.steps[2]["index"] == 0x414B


def test_sub_index_is_parsed_as_integer(tmp_path):
    path = tmp_path / "sub_index.yaml"
    path.write_text(
        "name: sub index parse test\n"
        "nodes: [1]\n"
        "steps:\n"
        "  - sdo_write: {index: 0x6091, sub: 0x01, value: 10}\n",
        encoding="utf-8",
    )
    scenario = load_scenario(str(path))
    step = scenario.steps[0]
    assert step["index"] == 0x6091
    assert step["sub"] == 1
    assert isinstance(step["sub"], int)
    assert step["value"] == 10


def test_relay_step_is_parsed():
    import io
    import os
    import tempfile

    from omsim.apps.scenario import load_scenario

    doc = "name: relay\nnodes: [1]\nsteps:\n  - relay: off\n  - relay: on\n"
    handle, path = tempfile.mkstemp(suffix=".yaml")
    os.close(handle)
    try:
        with io.open(path, "w", encoding="utf-8") as out:
            out.write(doc)
        scenario = load_scenario(path)
    finally:
        os.remove(path)

    assert [s["kind"] for s in scenario.steps] == ["relay", "relay"]
    # YAML の off/on は bool として読まれる。
    assert scenario.steps[0]["value"] is False
    assert scenario.steps[1]["value"] is True
