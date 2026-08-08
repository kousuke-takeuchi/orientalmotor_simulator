import pytest

from omsim.node.eds import DEFAULT_EDS_PATH, find_eds, load_eds


def test_loads_v400_eds():
    od = load_eds(DEFAULT_EDS_PATH)
    assert 0x6040 in od
    assert 0x6041 in od
    assert 0x60FF in od
    assert 0x4148 in od


def test_manufacturer_parameter_defaults_match_eds():
    od = load_eds(DEFAULT_EDS_PATH)
    assert od[0x414B].default == 1
    assert od[0x415F].default == 10000
    assert od[0x4186].default == 3000
    assert od[0x41CA].default == 1
    assert od[0x4735].default == 1000


def test_find_eds_accepts_bare_filename():
    assert find_eds("BLVD-KRD_CANopen_V400.eds").endswith("BLVD-KRD_CANopen_V400.eds")


def test_find_eds_raises_on_unknown():
    with pytest.raises(FileNotFoundError):
        find_eds("does-not-exist.eds")
