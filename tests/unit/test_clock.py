from omsim.sim.clock import SimClock


def test_step_is_one_millisecond():
    assert SimClock.STEP_SECONDS == 0.001


def test_advance_increments_tick_and_time():
    clock = SimClock(realtime=False)
    assert clock.tick_count == 0
    assert clock.now == 0.0
    dt = clock.advance()
    assert dt == 0.001
    assert clock.tick_count == 1
    assert abs(clock.now - 0.001) < 1e-12


def test_advance_for_is_deterministic():
    clock = SimClock(realtime=False)
    assert clock.advance_for(1.0) == 1000
    assert clock.tick_count == 1000
    assert abs(clock.now - 1.0) < 1e-9


def test_time_does_not_drift_over_many_steps():
    clock = SimClock(realtime=False)
    clock.advance_for(60.0)
    assert clock.tick_count == 60000
    assert abs(clock.now - 60.0) < 1e-9


def test_advance_yields_when_behind_schedule():
    import time as time_module
    import unittest.mock as mock

    from omsim.sim.clock import SimClock

    clock = SimClock(realtime=True)
    clock._wall_start = time_module.monotonic() - 10.0  # 大きく遅延させる
    with mock.patch("time.sleep") as fake_sleep:
        clock.advance()
    fake_sleep.assert_called_once_with(0)
