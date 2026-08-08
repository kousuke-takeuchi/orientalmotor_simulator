from omsim.driver.motor_plant import MotorPlant


def run(plant, seconds, command):
    steps = int(round(seconds / 0.001))
    for _ in range(steps):
        plant.step(0.001, command)


def test_starts_at_rest():
    plant = MotorPlant()
    assert plant.velocity == 0.0
    assert plant.position == 0
    assert plant.excited is False


def test_does_not_move_while_not_excited():
    plant = MotorPlant()
    run(plant, 1.0, 1000.0)
    assert plant.velocity == 0.0
    assert plant.position == 0


def test_follows_command_with_first_order_lag():
    plant = MotorPlant(time_constant=0.02)
    plant.excited = True
    run(plant, 0.02, 1000.0)
    # 時定数 1 本ぶんで 63% 前後
    assert 550.0 < plant.velocity < 700.0


def test_settles_at_the_command_velocity():
    plant = MotorPlant(time_constant=0.02)
    plant.excited = True
    run(plant, 1.0, 1000.0)
    assert abs(plant.velocity - 1000.0) < 1.0


def test_position_integrates_velocity():
    plant = MotorPlant(time_constant=0.001)
    plant.excited = True
    run(plant, 1.0, 1000.0)
    assert 950 <= plant.position <= 1000


def test_position_is_an_integer():
    plant = MotorPlant(time_constant=0.001)
    plant.excited = True
    run(plant, 0.1, 333.0)
    assert isinstance(plant.position, int)


def test_reverse_command_drives_position_negative():
    plant = MotorPlant(time_constant=0.001)
    plant.excited = True
    run(plant, 1.0, -1000.0)
    assert plant.position < 0


def test_losing_excitation_coasts_to_zero():
    plant = MotorPlant(time_constant=0.02)
    plant.excited = True
    run(plant, 1.0, 1000.0)
    plant.excited = False
    run(plant, 1.0, 1000.0)
    assert abs(plant.velocity) < 1.0


def test_torque_rises_while_accelerating_and_settles_to_load():
    plant = MotorPlant(time_constant=0.02, load_torque_permille=50.0, inertia_gain=1e-3)
    plant.excited = True
    run(plant, 0.005, 100000.0)
    accelerating = plant.torque_permille
    run(plant, 2.0, 100000.0)
    settled = plant.torque_permille
    assert accelerating > settled
    assert abs(settled - 50.0) < 1.0


def test_preset_position_overwrites_position():
    plant = MotorPlant()
    plant.preset_position(12345)
    assert plant.position == 12345


def test_reset_returns_to_rest():
    plant = MotorPlant(time_constant=0.001)
    plant.excited = True
    run(plant, 0.5, 1000.0)
    plant.reset()
    assert plant.velocity == 0.0
    assert plant.position == 0


def test_two_plants_are_independent():
    a, b = MotorPlant(time_constant=0.001), MotorPlant(time_constant=0.001)
    a.excited = True
    run(a, 0.5, 1000.0)
    assert b.velocity == 0.0
    assert b.position == 0
