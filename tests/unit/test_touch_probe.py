"""touch probe (60B8h-60BDh / 60D5h-60D8h)。HP-5143E 実測。

60B8h: bit0 有効化 / bit1 連続 / bit2 トリガ源 / bit4 正エッジ採取 / bit5 負エッジ採取
       probe 2 は bit8/9/10/12/13
60B9h: bit0 probe1 有効 / bit1 正エッジ保持 / bit2 負エッジ保持 (probe2 は bit8/9/10)
"""
import pytest

from omsim.driver.errors import ObjectAccessError
from omsim.driver.model import DriverModel

P1_ENABLE = 1 << 0
P1_CONTINUOUS = 1 << 1
P1_POSITIVE = 1 << 4
P1_NEGATIVE = 1 << 5
P2_ENABLE = 1 << 8
P2_POSITIVE = 1 << 12


def model_at(position=1234):
    model = DriverModel(node_id=1)
    model.plant.preset_position(position)
    model.step(0.001)
    return model


def test_default_function_matches_the_eds():
    assert DriverModel(node_id=1).read_object(0x60B8) == 0x3131


def test_status_reports_enabled_probes():
    model = model_at()
    model.write_object(0x60B8, 0, P1_ENABLE | P2_ENABLE)
    assert model.read_object(0x60B9) & (1 << 0)
    assert model.read_object(0x60B9) & (1 << 8)


def test_disabled_probe_does_not_latch():
    model = model_at()
    model.write_object(0x60B8, 0, 0)
    model.trigger_touch_probe(1, "positive")
    assert model.read_object(0x60B9) & (1 << 1) == 0


def test_positive_edge_latches_the_position():
    model = model_at(position=5000)
    model.write_object(0x60B8, 0, P1_ENABLE | P1_POSITIVE)
    model.trigger_touch_probe(1, "positive")
    assert model.read_object(0x60BA) == 5000
    assert model.read_object(0x60B9) & (1 << 1)
    assert model.read_object(0x60D5) == 1


def test_negative_edge_latches_separately():
    model = model_at(position=7000)
    model.write_object(0x60B8, 0, P1_ENABLE | P1_NEGATIVE)
    model.trigger_touch_probe(1, "negative")
    assert model.read_object(0x60BB) == 7000
    assert model.read_object(0x60B9) & (1 << 2)
    assert model.read_object(0x60D6) == 1


def test_edge_not_selected_is_ignored():
    model = model_at()
    model.write_object(0x60B8, 0, P1_ENABLE | P1_POSITIVE)
    model.trigger_touch_probe(1, "negative")
    assert model.read_object(0x60B9) & (1 << 2) == 0


def test_single_trigger_keeps_the_first_value():
    model = model_at(position=100)
    model.write_object(0x60B8, 0, P1_ENABLE | P1_POSITIVE)
    model.trigger_touch_probe(1, "positive")
    model.plant.preset_position(900)
    model.trigger_touch_probe(1, "positive")
    assert model.read_object(0x60BA) == 100     # 最初のイベントだけ
    assert model.read_object(0x60D5) == 1


def test_continuous_mode_updates_every_trigger():
    model = model_at(position=100)
    model.write_object(0x60B8, 0, P1_ENABLE | P1_CONTINUOUS | P1_POSITIVE)
    model.trigger_touch_probe(1, "positive")
    model.plant.preset_position(900)
    model.trigger_touch_probe(1, "positive")
    assert model.read_object(0x60BA) == 900
    assert model.read_object(0x60D5) == 2


def test_disabling_a_probe_clears_its_stored_values():
    model = model_at(position=100)
    model.write_object(0x60B8, 0, P1_ENABLE | P1_POSITIVE)
    model.trigger_touch_probe(1, "positive")
    model.write_object(0x60B8, 0, 0)
    assert model.read_object(0x60B9) & (1 << 1) == 0
    assert model.read_object(0x60D5) == 0


def test_probe_2_is_independent():
    model = model_at(position=4242)
    model.write_object(0x60B8, 0, P1_ENABLE | P1_POSITIVE | P2_ENABLE | P2_POSITIVE)
    model.trigger_touch_probe(2, "positive")
    assert model.read_object(0x60BC) == 4242
    assert model.read_object(0x60B9) & (1 << 9)
    assert model.read_object(0x60B9) & (1 << 1) == 0   # probe1 は未取得


def test_zsg_trigger_source_is_rejected():
    """bit2/bit10 の ZSG-N (index pulse) 源は未実装。黙って USR-LAT-IN 扱いにしない。"""
    model = model_at()
    with pytest.raises(ObjectAccessError):
        model.write_object(0x60B8, 0, P1_ENABLE | (1 << 2))


def test_unknown_probe_or_edge_is_rejected():
    model = model_at()
    with pytest.raises(ValueError):
        model.trigger_touch_probe(3, "positive")
    with pytest.raises(ValueError):
        model.trigger_touch_probe(1, "sideways")


def test_validate_object_does_not_clear_stored_probe_values():
    """60B8h の検証 (SDO 受信時) が実モデルのラッチ値を消してしまわないこと。

    60B8h の writer は「無効化されたら保持値を捨てる」副作用を持つ。
    _SHADOW_DEEP_ATTRS に touch probe の入れ物が入っていないと、
    probe を無効化する値を SDO で書いた瞬間 (キューに積む前の検証段階) に
    実モデルのラッチ値が消える。
    """
    model = model_at(position=321)
    model.write_object(0x60B8, 0, P1_ENABLE | P1_POSITIVE)
    model.trigger_touch_probe(1, "positive")
    assert model.read_object(0x60BA) == 321

    model.validate_object(0x60B8, 0, 0)   # 無効化を「検証だけ」する
    assert model.read_object(0x60BA) == 321
    assert model.read_object(0x60D5) == 1
