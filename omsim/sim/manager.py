"""複数ノードを 1 プロセスで同時に進める。"""
import collections

from omsim.driver.model import DriverModel
from omsim.node.eds import load_eds
from omsim.node.od_bridge import boot_local_node, build_local_node
from omsim.sim.clock import SimClock

NodeSpec = collections.namedtuple("NodeSpec", ["node_id", "eds", "mxex"])
NodeSpec.__new__.__defaults__ = (None,)


class NodeManager(object):
    def __init__(self, specs, network=None, realtime=True):
        self.clock = SimClock(realtime=realtime)
        self.network = network
        self.models = {}
        self.nodes = {}
        self._started = False
        for spec in specs:
            od = load_eds(spec.eds)
            model = DriverModel(node_id=spec.node_id)
            self.models[spec.node_id] = model
            self.nodes[spec.node_id] = build_local_node(spec.node_id, od, model)

    def start(self):
        if self.network is None or self._started:
            return
        for node in self.nodes.values():
            self.network[node.id] = node
            # 実機と同様、初期化後は自律的に boot-up を送出し PRE-OPERATIONAL へ
            # 遷移する。起動処理自体はノード個別の責務のため od_bridge 側に置く。
            boot_local_node(node)
        self._started = True

    def stop(self):
        if self.network is None or not self._started:
            return
        for node in self.nodes.values():
            node.remove_network()
        self._started = False

    def step(self):
        dt = self.clock.advance()
        for model in self.models.values():
            model.step(dt)

    def run_for(self, seconds):
        steps = int(round(seconds / SimClock.STEP_SECONDS))
        for _ in range(steps):
            self.step()

    def snapshot(self):
        return {
            "sim_time": self.clock.now,
            "nodes": dict(
                (node_id, model.snapshot()) for node_id, model in self.models.items()
            ),
        }
