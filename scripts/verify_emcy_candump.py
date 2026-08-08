"""修正1の目視確認用: vcan0 に実際に EMCY フレームが出ることを candump 相当で確認する。

`python3 scripts/verify_emcy_candump.py` として VM 上 (vcan0 前提) で実行する。
検証専用のスクリプトで、pytest スイートには含めない。
"""
import time

from omsim.can.bus import close_network, open_network
from omsim.node.eds import DEFAULT_EDS_PATH
from omsim.sim.manager import NodeManager, NodeSpec


def main():
    network = open_network(channel="vcan0")
    specs = [NodeSpec(node_id=1, eds=DEFAULT_EDS_PATH)]
    manager = NodeManager(specs, network=network, realtime=False)
    manager.start()
    try:
        model = manager.models[1]
        print("inject_alarm(0x30, 0x2310, error_register=0x21)")
        model.inject_alarm(0x30, 0x2310, error_register=0x21)
        manager.run_for(0.2)
        time.sleep(0.2)
    finally:
        manager.stop()
        close_network(network)


if __name__ == "__main__":
    main()
