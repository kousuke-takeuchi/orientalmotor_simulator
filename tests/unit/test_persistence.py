"""パラメータの保存 / 既定値復帰。HP-5143E 1010h / 1011h 実測。

署名は "save" (0x65766173) と "load" (0x64616F6C)。
sub1 = 全パラメータ、sub2 = 通信パラメータ (1000h-1FFFh) のみ。
署名が違えば abort 0800002xh。
"""
import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import DriverModel

SAVE = 0x65766173
LOAD = 0x64616F6C


def test_signatures_match_the_manual():
    from omsim.driver.persistence import LOAD_SIGNATURE, SAVE_SIGNATURE

    assert SAVE_SIGNATURE == SAVE
    assert LOAD_SIGNATURE == LOAD
    # "save" / "load" を LSB から並べた値であること
    assert bytes([SAVE & 0xFF, (SAVE >> 8) & 0xFF,
                  (SAVE >> 16) & 0xFF, (SAVE >> 24) & 0xFF]) == b"save"
    assert bytes([LOAD & 0xFF, (LOAD >> 8) & 0xFF,
                  (LOAD >> 16) & 0xFF, (LOAD >> 24) & 0xFF]) == b"load"


def test_highest_sub_index_is_two():
    model = DriverModel(node_id=1)
    assert model.read_object(0x1010, 0) == 2
    assert model.read_object(0x1011, 0) == 2


def test_wrong_signature_is_rejected():
    model = DriverModel(node_id=1)
    for index in (0x1010, 0x1011):
        with pytest.raises(ObjectAccessError) as exc:
            model.write_object(index, 1, 0x12345678)
        assert exc.value.abort_code == 0x08000020


def test_save_then_change_then_restore_brings_back_the_saved_value():
    model = DriverModel(node_id=1)
    model.write_object(0x6083, 0, 2000)
    model.write_object(0x1010, 1, SAVE)
    model.write_object(0x6083, 0, 5000)
    assert model.read_object(0x6083) == 5000
    model.restore_saved_parameters()
    assert model.read_object(0x6083) == 2000


def test_restore_defaults_resets_application_parameters():
    model = DriverModel(node_id=1)
    model.write_object(0x6083, 0, 5000)
    model.write_object(0x6084, 0, 5000)
    model.write_object(0x1011, 1, LOAD)
    assert model.read_object(0x6083) == 1000    # EDS 既定値
    assert model.read_object(0x6084) == 1000


def test_restore_communication_defaults_only_touches_1000_to_1fff():
    model = DriverModel(node_id=1)
    model.write_object(0x6083, 0, 5000)          # アプリ側
    model.write_object(0x1006, 0, 20000)         # 通信側
    model.write_object(0x1011, 2, LOAD)
    assert model.read_object(0x1006) == 0        # 通信パラメータは既定値へ
    assert model.read_object(0x6083) == 5000     # アプリ側はそのまま


def test_save_communication_only_snapshots_1000_to_1fff():
    model = DriverModel(node_id=1)
    model.write_object(0x1006, 0, 5000)
    model.write_object(0x6083, 0, 3000)
    model.write_object(0x1010, 2, SAVE)
    model.write_object(0x1006, 0, 7000)
    model.write_object(0x6083, 0, 4000)
    model.restore_saved_parameters()
    assert model.read_object(0x1006) == 5000
    assert model.read_object(0x6083) == 4000     # 保存対象外なので戻らない


def test_reading_reports_the_storage_capability():
    """読み出しは保存機能の情報を返す (bit0 = コマンドで保存できる)。"""
    model = DriverModel(node_id=1)
    assert model.read_object(0x1010, 1) & 1
    assert model.read_object(0x1011, 1) & 1


def test_validate_object_does_not_actually_store_or_restore():
    """1010h/1011h の検証 (SDO 受信時) が実モデルを保存/復帰させないこと。

    writer が保存領域とモデル全体を書き換えるので、_SHADOW_DEEP_ATTRS の
    漏れがあると SDO を受けた瞬間 (キューに積む前) に効いてしまう。
    """
    model = DriverModel(node_id=1)
    model.write_object(0x6083, 0, 2000)
    model.write_object(0x1010, 1, SAVE)      # 2000 を保存
    model.write_object(0x6083, 0, 5000)

    model.validate_object(0x1010, 1, SAVE)   # 検証だけ (5000 を保存してはいけない)
    model.restore_saved_parameters()
    assert model.read_object(0x6083) == 2000

    model.write_object(0x6083, 0, 5000)
    model.validate_object(0x1011, 1, LOAD)   # 検証だけ (既定値へ戻してはいけない)
    assert model.read_object(0x6083) == 5000


def test_validate_object_does_not_store_communication_parameters_either():
    """1010h:02 は保存領域を in-place 更新するため、共有していると漏れる。"""
    model = DriverModel(node_id=1)
    model.write_object(0x1006, 0, 5000)
    model.write_object(0x1010, 2, SAVE)      # 5000 を保存
    model.write_object(0x1006, 0, 9000)

    model.validate_object(0x1010, 2, SAVE)   # 検証だけ (9000 を保存してはいけない)
    model.restore_saved_parameters()
    assert model.read_object(0x1006) == 5000
