"""アドレスコード表の抽出。HP-5141J「7 アドレスコード一覧」実測。"""
from scripts.extract_address_codes import parse_address_codes

SAMPLE = """
  800     801   HWTO入力OFF時アラーム発生   の設定です                                       400
  802     803   HWTO-2重系異常検出遅延時間                                                401
  816     817   ETO解除無効時間                                                        408
  1660    1661                                                        830
  111     115   壊れた行 (下位が上位+1 でない)                                             55
  900     901   NET-ID が上位//2 でない行                                                999
"""


def test_extracts_rows_that_satisfy_the_invariant():
    rows, skipped = parse_address_codes(SAMPLE)
    netids = [row.netid for row in rows]
    assert netids == [400, 401, 408, 830]


def test_netid_is_half_of_the_modbus_upper_address():
    """実測で成り立つ関係。mxex の netid と Modbus アドレスをつなぐ鍵。"""
    rows, _skipped = parse_address_codes(SAMPLE)
    for row in rows:
        assert row.netid == row.modbus_upper // 2
        assert row.modbus_lower == row.modbus_upper + 1


def test_rows_breaking_the_invariant_are_counted_not_dropped_silently():
    _rows, skipped = parse_address_codes(SAMPLE)
    assert skipped == 2


def test_names_are_kept_when_present_on_the_same_line():
    rows, _skipped = parse_address_codes(SAMPLE)
    by_netid = dict((row.netid, row.name) for row in rows)
    assert "HWTO入力OFF時アラーム発生" in by_netid[400]
    assert by_netid[830] == ""   # 名称が別行に折れている行は空で残す
