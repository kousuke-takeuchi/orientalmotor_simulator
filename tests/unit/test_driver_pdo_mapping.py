import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import DriverModel
from omsim.driver.pdo import pack_mapping_entry


def test_default_rpdo1_mapping_is_controlword_only():
    model = DriverModel(node_id=1)
    assert model.rpdo_mapping[0].count == 1
    assert model.rpdo_mapping[0].entries[0].index == 0x6040
    assert model.rpdo_mapping[0].entries[0].length_bits == 16


def test_default_rpdo3_mapping_matches_eds():
    model = DriverModel(node_id=1)
    entries = model.rpdo_mapping[2].entries
    assert entries[0].index == 0x6040 and entries[0].length_bits == 16
    assert entries[1].index == 0x607A and entries[1].length_bits == 32


def test_default_tpdo1_mapping_is_statusword_only():
    model = DriverModel(node_id=1)
    assert model.tpdo_mapping[0].count == 1
    assert model.tpdo_mapping[0].entries[0].index == 0x6041


def test_read_mapping_sub0_returns_count():
    model = DriverModel(node_id=1)
    assert model.read_object(0x1601, 0) == 2


def test_read_mapping_entry_returns_packed_value():
    model = DriverModel(node_id=1)
    assert model.read_object(0x1600, 1) == pack_mapping_entry(0x6040, 0, 16)


def test_cannot_change_mapping_entry_while_pdo_is_enabled():
    model = DriverModel(node_id=1)
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x1600, 1, pack_mapping_entry(0x6060, 0, 8))
    assert exc.value.abort_code == 0x08000022  # ABORT_DEVICE_STATE


def test_can_change_mapping_entry_after_disabling_the_pdo():
    model = DriverModel(node_id=1)
    disabled_cob_id = model.rpdo_comm[0].cob_id | (1 << 31)
    model.write_object(0x1400, 1, disabled_cob_id)
    model.write_object(0x1600, 0, 0)  # マッピングを一旦無効化 (4.7.1 手順②)
    model.write_object(0x1600, 1, pack_mapping_entry(0x6060, 0, 8))
    model.write_object(0x1600, 0, 1)  # 有効化 (手順④)
    assert model.rpdo_mapping[0].entries[0].index == 0x6060


def test_mapping_sub0_cannot_exceed_four():
    model = DriverModel(node_id=1)
    model.write_object(0x1400, 1, model.rpdo_comm[0].cob_id | (1 << 31))
    model.write_object(0x1600, 0, 0)
    with pytest.raises(ObjectAccessError):
        model.write_object(0x1600, 0, 5)


def test_non_byte_aligned_length_is_rejected():
    """このフェーズはバイト境界マッピングのみ対応 (EDS の既定マッピングが
    全てバイト境界であるため)。ビット単位のパッキングは明示的に拒否する。"""
    model = DriverModel(node_id=1)
    model.write_object(0x1400, 1, model.rpdo_comm[0].cob_id | (1 << 31))
    model.write_object(0x1600, 0, 0)
    with pytest.raises(ObjectAccessError):
        model.write_object(0x1600, 1, pack_mapping_entry(0x6040, 0, 12))
