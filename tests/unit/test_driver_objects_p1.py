"""P1 で pitakuru 疎通のために追加した 7 オブジェクトのテスト。

対象: 6072h (Max torque), 4032h (Direct torque limit), 1003h (Pre-defined
error field, sub0 + sub1-10), 60FEh:01 (Digital outputs), 409Bh (Main power
supply current), 6081h (Profile velocity), 1016h:01 (Consumer heartbeat time)。
"""
import pytest

from omsim.driver.errors import ABORT_VALUE_RANGE, ObjectAccessError
from omsim.driver.model import DriverModel


def make_model(node_id=1):
    return DriverModel(node_id=node_id)


# --- 6072h Max torque ---

def test_max_torque_default_is_10000():
    assert make_model().read_object(0x6072) == 10000


def test_max_torque_write_then_read_back():
    model = make_model()
    model.write_object(0x6072, 0, 5000)
    assert model.read_object(0x6072) == 5000


def test_max_torque_rejects_out_of_range():
    model = make_model()
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x6072, 0, 10001)
    assert exc.value.abort_code == ABORT_VALUE_RANGE
    with pytest.raises(ObjectAccessError):
        model.write_object(0x6072, 0, -1)


# --- 4032h Direct data operation torque limiting value ---

def test_direct_torque_limit_default_is_10000():
    assert make_model().read_object(0x4032) == 10000


def test_direct_torque_limit_write_then_read_back():
    model = make_model()
    model.write_object(0x4032, 0, 3000)
    assert model.read_object(0x4032) == 3000


def test_direct_torque_limit_rejects_out_of_range():
    model = make_model()
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x4032, 0, 10001)
    assert exc.value.abort_code == ABORT_VALUE_RANGE
    with pytest.raises(ObjectAccessError):
        model.write_object(0x4032, 0, -1)


# --- 指摘1: 6072h と 4032h は別オブジェクトであり独立していること ---

def test_6072h_and_4032h_are_independent_instance_variables():
    model = make_model()
    model.write_object(0x4032, 0, 3000)
    # 4032h に書いても 6072h は既定値のまま変化しない。
    assert model.read_object(0x6072) == 10000

    model.write_object(0x6072, 0, 7000)
    # 6072h に書いても直前の 4032h の値は変化しない。
    assert model.read_object(0x4032) == 3000
    assert model.read_object(0x6072) == 7000


# --- 60FEh:01 Digital outputs ---

def test_digital_outputs_default_is_zero():
    assert make_model().read_object(0x60FE, 1) == 0


def test_digital_outputs_write_then_read_back():
    model = make_model()
    model.write_object(0x60FE, 1, 0x00004001)
    assert model.read_object(0x60FE, 1) == 0x00004001


# --- 409Bh Main power supply current (読み専用スタブ) ---

def test_main_power_current_reads_zero():
    assert make_model().read_object(0x409B) == 0


def test_main_power_current_is_not_writable():
    model = make_model()
    with pytest.raises(ObjectAccessError):
        model.write_object(0x409B, 0, 100)


# --- 6081h Profile velocity ---

def test_profile_velocity_default_is_one():
    assert make_model().read_object(0x6081) == 1


def test_profile_velocity_write_then_read_back():
    model = make_model()
    model.write_object(0x6081, 0, 1500)
    assert model.read_object(0x6081) == 1500


def test_profile_velocity_rejects_negative():
    model = make_model()
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x6081, 0, -1)
    assert exc.value.abort_code == ABORT_VALUE_RANGE


# --- 1016h:01 Consumer heartbeat time ---

def test_consumer_heartbeat_time_default_is_zero():
    assert make_model().read_object(0x1016, 1) == 0


def test_consumer_heartbeat_time_write_then_read_back():
    model = make_model()
    model.write_object(0x1016, 1, 500)
    assert model.read_object(0x1016, 1) == 500


# --- 1003h Pre-defined error field ---

def test_error_field_sub0_is_zero_with_no_history():
    assert make_model().read_object(0x1003, 0) == 0


def test_error_field_sub1_to_10_are_read_only():
    model = make_model()
    for sub in range(1, 11):
        with pytest.raises(ObjectAccessError):
            model.write_object(0x1003, sub, 1)


def test_error_field_sub0_counts_history_and_subs_return_history():
    model = make_model()
    model.inject_alarm(0x30, 0x2310)
    assert model.read_object(0x1003, 0) == 1
    assert model.read_object(0x1003, 1) == 0x30
    # まだ発生していない sub は 0 を返す。
    assert model.read_object(0x1003, 2) == 0


def test_error_field_sub0_write_zero_clears_history():
    model = make_model()
    model.inject_alarm(0x30, 0x2310)
    assert model.read_object(0x1003, 0) == 1
    model.write_object(0x1003, 0, 0)
    assert model.read_object(0x1003, 0) == 0
    assert model.read_object(0x1003, 1) == 0


def test_error_field_sub0_rejects_nonzero_write():
    model = make_model()
    with pytest.raises(ObjectAccessError) as exc:
        model.write_object(0x1003, 0, 1)
    assert exc.value.abort_code == ABORT_VALUE_RANGE


# --- 2 台のインスタンスで値が混ざらないこと ---

def test_two_instances_do_not_share_p1_object_state():
    a, b = make_model(node_id=1), make_model(node_id=2)

    a.write_object(0x6072, 0, 1000)
    a.write_object(0x4032, 0, 2000)
    a.write_object(0x60FE, 1, 0x1)
    a.write_object(0x6081, 0, 300)
    a.write_object(0x1016, 1, 50)
    a.inject_alarm(0x30, 0x2310)

    assert b.read_object(0x6072) == 10000
    assert b.read_object(0x4032) == 10000
    assert b.read_object(0x60FE, 1) == 0
    assert b.read_object(0x6081) == 1
    assert b.read_object(0x1016, 1) == 0
    assert b.read_object(0x1003, 0) == 0

    assert a.read_object(0x6072) == 1000
    assert a.read_object(0x4032) == 2000
    assert a.read_object(0x60FE, 1) == 0x1
    assert a.read_object(0x6081) == 300
    assert a.read_object(0x1016, 1) == 50
    assert a.read_object(0x1003, 0) == 1


# --- 指摘3: スタブ登録の仕組み ---

def test_stub_objects_lists_the_four_unimplemented_objects():
    stubs = make_model().stub_objects()
    stub_keys = set((index, sub) for index, sub, _reason in stubs)
    # 1016h (Heartbeat consumer) は P3 で実働になったのでスタブではない。
    assert (0x1016, 1) not in stub_keys
    assert (0x409B, 0) in stub_keys
    assert (0x60FE, 1) in stub_keys
    assert (0x6081, 0) in stub_keys
    # 1003h (エラー履歴) は実際に機能しているのでスタブではない。
    assert (0x1003, 0) not in stub_keys
    # 最終ブランチレビュー指摘4: 6072h/4032h は値を保持・読み返しできるが
    # MotorPlant が参照しないため運転には効かない。「実装したつもりで
    # 呼ばれない」ことを --list-stubs で機械的に確認できるよう、スタブとして
    # 登録されている（P1 時点ではここが漏れていた）。
    assert (0x6072, 0) in stub_keys
    assert (0x4032, 0) in stub_keys


def test_stub_objects_reasons_are_non_empty_strings():
    for _index, _sub, reason in make_model().stub_objects():
        assert isinstance(reason, str)
        assert len(reason) > 0
