"""mxex ローダと diff。netid == CANopen index - 0x4000 (bank 1) を使う。"""
import io
import os
import tempfile

from omsim.apps.mxex import apply_mxex, diff_mxex, mxex_to_objects
from omsim.driver.model import DriverModel

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RIGHT = os.path.join(HERE, "docs", "oriental_motor", "日本アクセス_右モーター.mxex")
LEFT = os.path.join(HERE, "docs", "oriental_motor", "日本アクセス_左モーター.mxex")


def write_mxex(values):
    body = "".join(
        '<netid id="{}" val="{}"><att key="bank" val="1" /></netid>'.format(k, v)
        for k, v in values.items())
    handle, path = tempfile.mkstemp(suffix=".mxex")
    os.close(handle)
    with io.open(path, "w", encoding="utf-8") as out:
        out.write('﻿<?xml version="1.0"?><FileDataTree><NetIds>'
                  + body + "</NetIds></FileDataTree>")
    return path


def test_netid_maps_to_the_manufacturer_object_index():
    # 4169h = (HOME) 2 センサ原点復帰の戻りステップ数 -> netid 0x169 = 361
    objects = mxex_to_objects({361: 25})
    assert objects == {0x4169: 25}


def test_apply_writes_implemented_objects_only():
    model = DriverModel(node_id=1)
    path = write_mxex({0x169: 25, 0x032: 40, 0x7FF: 1})
    try:
        report = apply_mxex(model, path)
    finally:
        os.remove(path)
    assert model.read_object(0x4169) == 25         # passthrough だが読み書きできる
    assert model.read_object(0x4032) == 40         # トルク制限値
    assert report["applied"] == 2
    assert report["unknown"] == 1                  # 47FFh は OD に無い
    assert 0x47FF in report["unknown_indexes"]


def test_apply_reports_rejected_values_without_stopping():
    model = DriverModel(node_id=1)
    path = write_mxex({0x032: 99999})              # 4032h は 0-10000
    try:
        report = apply_mxex(model, path)
    finally:
        os.remove(path)
    assert report["applied"] == 0
    assert report["rejected"] == 1


def test_diff_lists_only_the_differences():
    result = diff_mxex(RIGHT, LEFT)
    assert result["only_in_a"] == {}
    assert result["only_in_b"] == {}
    # 実測: 右/左で違うのは netid 17152 だけ (右 2 / 左 1)
    assert result["different"] == {17152: (2, 1)}


def test_diff_on_the_same_file_is_empty():
    result = diff_mxex(RIGHT, RIGHT)
    assert result["different"] == {}
