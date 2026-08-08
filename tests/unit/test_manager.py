from omsim.node.eds import DEFAULT_EDS_PATH
from omsim.sim.manager import NodeManager, NodeSpec


def make_manager(*node_ids):
    specs = [NodeSpec(node_id=i, eds=DEFAULT_EDS_PATH, mxex=None) for i in node_ids]
    return NodeManager(specs, network=None, realtime=False)


def test_creates_one_model_and_node_per_spec():
    manager = make_manager(1, 2)
    assert sorted(manager.models) == [1, 2]
    assert sorted(manager.nodes) == [1, 2]
    assert manager.models[1] is not manager.models[2]


def test_node_count_is_not_fixed_to_two():
    manager = make_manager(1, 2, 3, 7)
    assert sorted(manager.models) == [1, 2, 3, 7]


def test_step_advances_every_node_by_one_millisecond():
    manager = make_manager(1, 2)
    manager.step()
    assert abs(manager.models[1].sim_time - 0.001) < 1e-12
    assert abs(manager.models[2].sim_time - 0.001) < 1e-12


def test_run_for_advances_all_nodes_together():
    manager = make_manager(1, 2)
    manager.run_for(0.5)
    for model in manager.models.values():
        assert abs(model.sim_time - 0.5) < 1e-9


def test_snapshot_contains_every_node():
    manager = make_manager(1, 2)
    manager.step()
    snap = manager.snapshot()
    assert abs(snap["sim_time"] - 0.001) < 1e-12
    assert sorted(snap["nodes"]) == [1, 2]
    assert snap["nodes"][2]["node_id"] == 2


def test_sdo_cob_ids_do_not_collide_between_nodes():
    manager = make_manager(1, 2)
    assert manager.nodes[1].sdo.rx_cobid != manager.nodes[2].sdo.rx_cobid
    assert manager.nodes[1].emcy.cob_id != manager.nodes[2].emcy.cob_id
