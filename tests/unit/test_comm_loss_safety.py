"""通信途絶時の自動停止。

症状: マスタ (PC の motor_control_node) と通信が切れても、ドライバは直前の
速度指令のまま回り続ける。PC の電源が落ちると制御不能になる。

対策: CANopen の Heartbeat consumer (1016h) をドライバに設定し、マスタからの
Heartbeat が指定時間内に来なければアラームを出して無励磁 (= HWTO 相当の
フリーラン + 電磁ブレーキ保持) にする。
"""
from omsim.driver.model import MODE_PV, DriverModel

MASTER_NODE_ID = 0x7F
TIMEOUT_MS = 500


def running_model(target=200):
    model = DriverModel(node_id=1)
    model.step(0.001)
    model.write_object(0x6060, 0, MODE_PV)
    model.write_object(0x6083, 0, 6000)
    model.write_object(0x6084, 0, 6000)
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    model.write_object(0x60FF, 0, target)
    for _ in range(500):
        model.step(0.001)
    assert abs(model.actual_velocity_rpm - target) < 5
    return model


def run(model, milliseconds, heartbeat_every=None):
    """heartbeat_every [ms] を指定すると、その周期でマスタの Heartbeat を届ける。"""
    for tick in range(milliseconds):
        if heartbeat_every and tick % heartbeat_every == 0:
            model.on_heartbeat_received(MASTER_NODE_ID, model.sim_time)
        model.step(0.001)


def test_symptom_without_the_setting_the_motor_keeps_running():
    """修正前の症状: 通信が切れても直前の速度指令で回り続ける。"""
    model = running_model(target=200)
    run(model, 3000)                      # 3 秒間、マスタから何も来ない
    assert abs(model.actual_velocity_rpm - 200) < 5
    assert model.plant.excited is True


def test_heartbeat_timeout_stops_the_motor():
    """1016h を設定すると、0.5 秒の途絶で自動停止する。"""
    model = running_model(target=200)
    model.write_object(0x1016, 1, (MASTER_NODE_ID << 16) | TIMEOUT_MS)
    run(model, 200, heartbeat_every=100)   # 正常に届いている間は回り続ける
    assert abs(model.actual_velocity_rpm - 200) < 5

    run(model, 1000)                        # 途絶
    assert abs(model.actual_velocity_rpm) < 2
    assert model.plant.excited is False


def test_stop_is_the_same_shape_as_hwto():
    """停止の形は HWTO と同じ (無励磁 + 電磁ブレーキ保持)。"""
    model = running_model()
    model.write_object(0x1016, 1, (MASTER_NODE_ID << 16) | TIMEOUT_MS)
    run(model, 100, heartbeat_every=50)
    run(model, 1000)
    assert model.brake_engaged is True
    assert model.state_machine.state in ("fault", "fault-reaction-active")


def test_the_alarm_is_the_network_bus_error():
    model = running_model()
    model.write_object(0x1016, 1, (MASTER_NODE_ID << 16) | TIMEOUT_MS)
    run(model, 100, heartbeat_every=50)
    run(model, 1000)
    assert model.alarms.is_active
    assert model.alarms.error_code == 0x8130      # CiA301: node guarding / heartbeat
    assert model.snapshot()["alarm_name"] == "Network bus error"


def test_it_does_not_stop_while_the_master_keeps_talking():
    model = running_model(target=200)
    model.write_object(0x1016, 1, (MASTER_NODE_ID << 16) | TIMEOUT_MS)
    run(model, 3000, heartbeat_every=100)
    assert abs(model.actual_velocity_rpm - 200) < 5
    assert not model.alarms.is_active


def test_timeout_is_measured_from_the_last_heartbeat():
    model = running_model()
    model.write_object(0x1016, 1, (MASTER_NODE_ID << 16) | TIMEOUT_MS)
    run(model, 400, heartbeat_every=100)
    run(model, 400)                        # 途絶して 400ms (まだ 500ms 未満)
    assert not model.alarms.is_active
    run(model, 200)                        # 合計 600ms
    assert model.alarms.is_active


def test_recovering_requires_a_fault_reset():
    """復帰は自動ではない。

    通信が戻るとアラーム自体は解けるが、CiA402 のステートマシンは fault に
    留まる。Controlword bit7 (Fault reset) を立ててから改めて enable する。
    「通信が戻った瞬間に勝手に動き出す」ことはない。
    """
    model = running_model()
    model.write_object(0x1016, 1, (MASTER_NODE_ID << 16) | TIMEOUT_MS)
    run(model, 100, heartbeat_every=50)
    run(model, 1000)
    assert model.alarms.is_active

    run(model, 100, heartbeat_every=50)    # 通信が戻る
    assert not model.alarms.is_active      # heartbeat 復帰でアラームは解ける
    assert model.state_machine.state == "fault"
    assert model.plant.excited is False     # まだ動かない

    model.write_object(0x6040, 0, 0x0080)   # Fault reset (bit7 の立ち上がり)
    model.step(0.001)
    for controlword in (0x0006, 0x0007, 0x000F):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    run(model, 300, heartbeat_every=50)
    assert model.plant.excited is True
