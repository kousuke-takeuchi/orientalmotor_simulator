import pytest

from omsim.sim.wiring import Cn4Wiring, WiringError


def test_standard_wiring_drives_both_channels_from_the_relay():
    wiring = Cn4Wiring.preset("standard")
    assert wiring.hwto_inputs(relay_energized=True) == (True, True)
    assert wiring.hwto_inputs(relay_energized=False) == (False, False)


def test_pitakuru_wiring_drives_only_hwto1_from_the_relay():
    """実機 (図面 08015VA-24M-AA-00): 安全リレーは HWTO1 だけ。HWTO2 は標準ジャンパ。"""
    wiring = Cn4Wiring.preset("pitakuru")
    assert wiring.hwto_inputs(relay_energized=True) == (True, True)
    assert wiring.hwto_inputs(relay_energized=False) == (False, True)


def test_none_wiring_jumpers_both_channels():
    """動力遮断機能を使わない配線 (付属ジャンパーで短絡)。"""
    wiring = Cn4Wiring.preset("none")
    assert wiring.hwto_inputs(relay_energized=False) == (True, True)


def test_open_source_is_always_off():
    wiring = Cn4Wiring(hwto1="open", hwto2="jumper")
    assert wiring.hwto_inputs(relay_energized=True) == (False, True)


def test_unknown_preset_is_rejected():
    with pytest.raises(WiringError):
        Cn4Wiring.preset("nonsense")


def test_unknown_source_is_rejected():
    with pytest.raises(WiringError):
        Cn4Wiring(hwto1="battery", hwto2="jumper")


def test_describe_lists_both_channels_and_the_cn4_pins():
    described = Cn4Wiring.preset("pitakuru").describe()
    assert described["hwto1"]["source"] == "relay"
    assert described["hwto1"]["pins"] == "CN4 11/12"
    assert described["hwto2"]["source"] == "jumper"
    assert described["hwto2"]["pins"] == "CN4 26/27"
