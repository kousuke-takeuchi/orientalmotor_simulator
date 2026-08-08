from omsim.driver.profile import TrapezoidProfile


def run(profile, seconds):
    steps = int(round(seconds / 0.001))
    for _ in range(steps):
        profile.step(0.001)
    return profile.command


def test_starts_at_zero():
    profile = TrapezoidProfile()
    assert profile.command == 0.0
    assert profile.at_target is True


def test_accelerates_at_the_configured_rate():
    profile = TrapezoidProfile(acceleration=1000.0)
    profile.set_target(1000.0)
    assert abs(run(profile, 0.5) - 500.0) < 1e-6


def test_stops_accelerating_at_the_target():
    profile = TrapezoidProfile(acceleration=1000.0)
    profile.set_target(100.0)
    assert abs(run(profile, 1.0) - 100.0) < 1e-6
    assert profile.at_target is True


def test_decelerates_with_the_deceleration_rate():
    profile = TrapezoidProfile(acceleration=1000.0, deceleration=500.0)
    profile.set_target(1000.0)
    run(profile, 2.0)
    profile.set_target(0.0)
    assert abs(run(profile, 1.0) - 500.0) < 1e-6


def test_reaches_zero_exactly_without_overshoot():
    profile = TrapezoidProfile(acceleration=1000.0, deceleration=1000.0)
    profile.set_target(100.0)
    run(profile, 1.0)
    profile.set_target(0.0)
    assert run(profile, 1.0) == 0.0


def test_negative_target_accelerates_in_reverse():
    profile = TrapezoidProfile(acceleration=1000.0)
    profile.set_target(-1000.0)
    assert abs(run(profile, 0.5) + 500.0) < 1e-6


def test_sign_reversal_passes_through_zero_using_deceleration_first():
    profile = TrapezoidProfile(acceleration=1000.0, deceleration=2000.0)
    profile.set_target(1000.0)
    run(profile, 2.0)
    profile.set_target(-1000.0)
    # 1000 -> 0 は deceleration 2000 なので 0.5s、その後 0 -> -500 は acceleration 1000 で 0.5s
    assert abs(run(profile, 0.5)) < 1e-6
    assert abs(run(profile, 0.5) + 500.0) < 1e-6


def test_reset_clears_command_and_target():
    profile = TrapezoidProfile()
    profile.set_target(500.0)
    run(profile, 0.1)
    profile.reset()
    assert profile.command == 0.0
    assert profile.target == 0.0
    assert profile.at_target is True


def test_two_profiles_are_independent():
    a = TrapezoidProfile(acceleration=1000.0)
    b = TrapezoidProfile(acceleration=1000.0)
    a.set_target(1000.0)
    run(a, 0.5)
    assert b.command == 0.0
