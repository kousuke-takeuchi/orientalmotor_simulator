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
