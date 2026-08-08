"""BLVD-KRD ドライバの挙動モデル。can / canopen を import しないこと。"""
from omsim.driver.objects import ObjectRouter


class DriverModel(object):
    """1 台のドライバ。状態は全てインスタンス変数に持つ。"""

    router = ObjectRouter()

    DEVICE_NAME = "BLVD-KRD"

    def __init__(self, node_id):
        self.node_id = node_id
        self.sim_time = 0.0

    # --- 外向きの窓口は以下の 4 つだけ ---

    def read_object(self, index, sub=0):
        return self.router.read(self, index, sub)

    def write_object(self, index, sub=0, value=0):
        self.router.write(self, index, sub, value)

    def step(self, dt):
        self.sim_time += dt

    def snapshot(self):
        return {"node_id": self.node_id, "sim_time": self.sim_time}

    # --- オブジェクトハンドラ ---

    @router.reader(0x1008)
    def _read_device_name(self, sub):
        return self.DEVICE_NAME
