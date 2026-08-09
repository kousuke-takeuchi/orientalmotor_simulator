from omsim.driver.alarm_model import EMCY_HEARTBEAT_ERROR
from omsim.driver.model import DriverModel


def test_default_guard_time_and_life_time_factor_are_zero():
    model = DriverModel(node_id=1)
    assert model.read_object(0x100C) == 0
    assert model.read_object(0x100D) == 0


def test_write_guard_time_and_life_time_factor():
    model = DriverModel(node_id=1)
    model.write_object(0x100C, 0, 100)
    model.write_object(0x100D, 0, 3)
    assert model.guard_time_ms == 100
    assert model.life_time_factor == 3


def test_configuring_heartbeat_consumer_parses_node_id_and_time():
    model = DriverModel(node_id=1)
    # sub1 raw = (node_id << 16) | time_ms
    model.write_object(0x1016, 1, (2 << 16) | 500)
    assert model.heartbeat_consumer_node_id == 2
    assert model.heartbeat_consumer_time_ms == 500


def test_heartbeat_consumer_raises_alarm_after_timeout():
    model = DriverModel(node_id=1)
    model.write_object(0x1016, 1, (2 << 16) | 500)
    for _ in range(600):  # 600ms 分ステップを進める (何も heartbeat を受けない)
        model.step(0.001)
    assert model.alarms.is_active
    assert model.alarms.error_code == EMCY_HEARTBEAT_ERROR


def test_heartbeat_consumer_does_not_raise_before_timeout():
    model = DriverModel(node_id=1)
    model.write_object(0x1016, 1, (2 << 16) | 500)
    for _ in range(400):
        model.step(0.001)
    assert not model.alarms.is_active


def test_receiving_heartbeat_resets_the_reference_time():
    model = DriverModel(node_id=1)
    model.write_object(0x1016, 1, (2 << 16) | 500)
    for _ in range(400):
        model.step(0.001)
    model.on_heartbeat_received(node_id=2, sim_time=model.sim_time)
    for _ in range(400):  # 合計 800ms 経過したが、400ms 前にリセットしたので猶予内
        model.step(0.001)
    assert not model.alarms.is_active


def test_heartbeat_consumer_disabled_when_node_id_is_zero():
    model = DriverModel(node_id=1)
    model.write_object(0x1016, 1, 0)  # node_id=0 は無効化
    for _ in range(2000):
        model.step(0.001)
    assert not model.alarms.is_active


def test_heartbeat_from_unrelated_node_is_ignored():
    model = DriverModel(node_id=1)
    model.write_object(0x1016, 1, (2 << 16) | 500)
    model.on_heartbeat_received(node_id=3, sim_time=0.0)  # 監視対象ではない
    for _ in range(600):
        model.step(0.001)
    # node 3 の受信は無視されるので、依然としてタイムアウトする
    assert model.alarms.is_active
