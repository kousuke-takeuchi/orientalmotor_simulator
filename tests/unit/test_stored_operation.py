"""ストアードデータ運転。HP-5141J 5 章 / 運転方式一覧 実測。

運転データを選び、START の立ち上がりで運転する。運転データ R/W は netid 空間
なので CANopen (SDO) からは触れない。ここでは model の API と mxex から設定する。
"""
import pytest

from omsim.driver.model import DriverModel
from omsim.driver.operation_data import OperationData, OperationDataTable

R_IO_BASE = 16
CW_ENABLE = 0x000F

TYPE_ABS = 1
TYPE_CONTINUOUS_VELOCITY = 16


def stored_model():
    """R-IN0 を START に割り付けた、励磁済みのモデル。"""
    model = DriverModel(node_id=1)
    model.set_remote_input_function(0, 32)      # R-IN0 = START
    model.step(0.001)
    for controlword in (0x0006, 0x0007, CW_ENABLE):
        model.write_object(0x6040, 0, controlword)
        model.step(0.001)
    return model


def run(model, milliseconds):
    for _ in range(milliseconds):
        model.step(0.001)


def press(model, bit):
    model.write_object(0x403E, 0, 1 << (R_IO_BASE + bit))
    model.step(0.001)


def release(model):
    model.write_object(0x403E, 0, 0)
    model.step(0.001)


# --- 運転データテーブル ---

def test_table_starts_with_defaults():
    table = OperationDataTable()
    assert table.size == 64
    assert table[0].operation_type == 0
    assert table[0].position == 0


def test_table_rejects_an_out_of_range_number():
    table = OperationDataTable()
    with pytest.raises(IndexError):
        table[64]


def test_entry_can_be_set():
    table = OperationDataTable()
    table.set(3, OperationData(operation_type=1, position=1000, velocity=200))
    assert table[3].position == 1000
    assert table[3].velocity == 200


def test_model_has_a_table_and_a_selected_number():
    model = DriverModel(node_id=1)
    assert model.operation_data.size == 64
    assert model.selected_data_number == 0


# --- 運転データ No. の選択 ---

def test_d_sel_bits_select_the_data_number():
    model = stored_model()
    # 既定割付では R-IN8-15 が D-SEL0-7。D-SEL0 と D-SEL2 -> 5 番
    model.write_object(0x403E, 0, (1 << (R_IO_BASE + 8)) | (1 << (R_IO_BASE + 10)))
    model.step(0.001)
    assert model.selected_data_number == 5


def test_net_selection_data_number_is_used_when_no_d_sel_is_on():
    model = stored_model()
    model.write_object(0x403D, 0, 7)
    model.step(0.001)
    assert model.selected_data_number == 7


# --- START ---

def test_start_runs_the_selected_data():
    model = stored_model()
    model.operation_data.set(2, OperationData(
        operation_type=TYPE_ABS, position=7200, velocity=300,
        acceleration=6000, deceleration=6000))
    model.write_object(0x403D, 0, 2)
    press(model, 0)
    run(model, 4000)
    assert abs(model.read_object(0x6064) - 7200) <= 30


def test_start_is_edge_triggered():
    model = stored_model()
    model.operation_data.set(1, OperationData(
        operation_type=TYPE_CONTINUOUS_VELOCITY, velocity=120,
        acceleration=6000, deceleration=6000))
    model.write_object(0x403D, 0, 1)
    press(model, 0)
    run(model, 500)
    assert abs(model.read_object(0x606C) - 120) < 5

    # START を押したまま別データを選んでも切り替わらない (立ち上がりが必要)
    model.operation_data.set(1, OperationData(
        operation_type=TYPE_CONTINUOUS_VELOCITY, velocity=300,
        acceleration=6000, deceleration=6000))
    run(model, 500)
    assert abs(model.read_object(0x606C) - 120) < 5

    release(model)
    press(model, 0)
    run(model, 800)
    assert abs(model.read_object(0x606C) - 300) < 8


def test_start_does_nothing_without_excitation():
    model = DriverModel(node_id=1)
    model.set_remote_input_function(0, 32)
    model.step(0.001)
    model.operation_data.set(0, OperationData(
        operation_type=TYPE_CONTINUOUS_VELOCITY, velocity=200,
        acceleration=6000, deceleration=6000))
    press(model, 0)
    run(model, 300)
    assert abs(model.read_object(0x606C)) < 1


def test_unimplemented_operation_type_in_a_data_entry_is_reported():
    """未実装の運転方式が入っていたら、黙って別の動きをしない。"""
    from omsim.driver.errors import NotImplementedObjectError

    model = stored_model()
    model.operation_data.set(0, OperationData(operation_type=7))   # 連続運転(位置制御)
    with pytest.raises(NotImplementedObjectError):
        model.start_stored_operation()
