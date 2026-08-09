"""アラームコード表。HP-5143E 4.5 と HP-5141J 8 章「1-2 アラーム一覧」実測。"""
import pytest

from omsim.driver.alarm_codes import (
    ALARM_CODES,
    COMMUNICATION_EMCY,
    ERROR_REGISTER_MANUFACTURER,
    alarm_name,
    emcy_for,
    error_register_for,
    is_resettable,
)


def test_manufacturer_emcy_is_ff_prefixed():
    """メーカ固有アラームの EMCY は 0xFF00 | アラームコード (実測)。"""
    assert emcy_for(0x30) == 0xFF30
    assert emcy_for(0x53) == 0xFF53
    assert emcy_for(0x68) == 0xFF68
    assert emcy_for(0xF3) == 0xFFF3


def test_error_register_is_81h_for_manufacturer_alarms():
    for code in ALARM_CODES:
        assert error_register_for(code) == ERROR_REGISTER_MANUFACTURER == 0x81


def test_every_code_from_the_manual_is_present():
    expected = [
        0x10, 0x20, 0x21, 0x22, 0x25, 0x26, 0x28, 0x29, 0x2A, 0x30, 0x31,
        0x41, 0x42, 0x44, 0x45, 0x4A, 0x50, 0x53, 0x55, 0x60, 0x61, 0x62,
        0x63, 0x64, 0x66, 0x67, 0x68, 0x6A, 0x70, 0x71, 0x81, 0x84, 0x85,
        0x8C, 0xF0, 0xF3,
    ]
    assert sorted(ALARM_CODES) == expected


def test_names_match_the_manual():
    assert alarm_name(0x30) == "Overload"
    assert alarm_name(0x53) == "HWTO input circuit error"
    assert alarm_name(0x67) == "Software overtravel"


def test_unknown_code_is_rejected():
    with pytest.raises(KeyError):
        alarm_name(0x99)


def test_reset_permission_matches_the_manual():
    """ALM-RST 入力で解除できないアラームがある (HP-5141J 8 章実測)。"""
    assert is_resettable(0x10) is True     # 位置偏差過大
    assert is_resettable(0x21) is True     # 主回路過熱
    assert is_resettable(0x20) is False    # 過電流
    assert is_resettable(0x28) is False    # エンコーダ異常
    assert is_resettable(0x29) is False    # 内部回路異常
    assert is_resettable(0x53) is False    # HWTO 入力回路異常


def test_communication_emcy_codes_use_the_cia301_values():
    assert COMMUNICATION_EMCY["node_guarding"] == (0x8130, 0x11)
    assert COMMUNICATION_EMCY["can_overrun"] == (0x8110, 0x11)
    assert COMMUNICATION_EMCY["pdo_length"] == (0x8210, 0x11)


# --- DriverModel からの注入 ---

def test_inject_alarm_derives_the_emcy_code_from_the_table():
    """コードだけ渡せば EMCY と error register は表から決まる。"""
    from omsim.driver.model import DriverModel

    model = DriverModel(node_id=1)
    model.inject_alarm(0x30)
    assert model.alarms.error_code == 0xFF30
    assert model.alarms.error_register == 0x81


def test_overload_emcy_matches_the_manual_not_the_generic_cia301_code():
    """過負荷は FF30h。CiA301 の汎用 2310h ではない (HP-5143E 4.5 実測)。"""
    from omsim.driver.alarm_model import EMCY_OVERLOAD

    assert EMCY_OVERLOAD == 0xFF30
