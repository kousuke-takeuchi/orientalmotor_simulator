import pytest

from omsim.driver.errors import (
    ABORT_NOT_IN_OD,
    ABORT_NOT_WRITABLE,
    ObjectAccessError,
)
from omsim.driver.model import DriverModel


def test_reports_its_node_id():
    assert DriverModel(node_id=3).snapshot()["node_id"] == 3


def test_device_name_is_readable():
    assert DriverModel(node_id=1).read_object(0x1008) == "BLVD-KRD"


def test_device_name_is_not_writable():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x1008, 0, 1)
    assert exc.value.abort_code == ABORT_NOT_WRITABLE


def test_unhandled_object_read_aborts_as_not_in_od():
    # 1018h:01 (Identity object, Vendor ID) は router に未登録。従来は
    # 黙って None を返し EDS の既定値へフォールスルーしていたが、
    # それは「実機と違う値が返るのに気付けない」P2 で塞いだ穴のため、
    # 未登録オブジェクトは abort するのが仕様になった。
    with pytest.raises(ObjectAccessError) as exc:
        DriverModel(node_id=1).read_object(0x1018, 1)
    assert exc.value.abort_code == ABORT_NOT_IN_OD


def test_step_accumulates_sim_time():
    model = DriverModel(node_id=1)
    for _ in range(1000):
        model.step(0.001)
    assert abs(model.sim_time - 1.0) < 1e-9
    assert abs(model.snapshot()["sim_time"] - 1.0) < 1e-9


def test_two_models_do_not_share_state():
    a, b = DriverModel(node_id=1), DriverModel(node_id=2)
    a.step(0.001)
    assert a.sim_time != b.sim_time
    assert b.sim_time == 0.0


def test_shadow_isolation_holds_for_every_registered_writer():
    """全 writer について、現在の値で validate_object しても実モデルは一切変化しない。

    すでに legal な値を書き戻すだけなので値の妥当性チェックは常に通り、
    writer 内部の副作用 (state_machine の遷移や alarms のリセット等) だけが
    実モデルに漏れていないかを機械的に確認できる。軽量化した _shadow() の
    対象リストに漏れがあれば、このテストが実モデルの変化として検出する。
    """
    from omsim.driver.errors import ObjectAccessError
    from omsim.driver.model import DriverModel

    model = DriverModel(node_id=1)
    model.state_machine.step(0.001)
    model.write_object(0x6040, 0, 0x0006)
    model.write_object(0x6040, 0, 0x0007)
    model.write_object(0x6040, 0, 0x000F)

    def deep_state():
        return (
            model.state_machine.statusword,
            model.state_machine.controlword,
            model.plant.excited,
            model.plant.position,
            model.alarms.active_alarm,
            tuple(model.alarms.history),
            tuple(sorted(model.passthrough_values.items())),
        )

    before = deep_state()
    for index, sub in sorted(DriverModel.router._writers):
        try:
            current = model.read_object(index, sub)
        except ObjectAccessError:
            continue
        if current is None:
            # 未書込みの passthrough は読み出すと None。書き戻せる値が無いので対象外。
            continue
        try:
            model.validate_object(index, sub, current)
        except ObjectAccessError:
            continue
        assert deep_state() == before, (
            "{:04X}h:{:02X} の validate_object が実モデルを変化させた".format(index, sub))


def test_validate_object_still_isolates_controlword_side_effects():
    from omsim.driver.model import DriverModel

    model = DriverModel(node_id=1)
    model.validate_object(0x6040, 0, 0x0006)
    assert model.state_machine.controlword == 0  # 検証だけでは実モデルは動かない
