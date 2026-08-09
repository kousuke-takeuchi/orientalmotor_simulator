import os

from scripts.mxex_dump import mxex_netids, parse_mxex_netids

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MXEX_DIR = os.path.join(HERE, "docs", "oriental_motor")
RIGHT = os.path.join(MXEX_DIR, "日本アクセス_右モーター.mxex")
LEFT = os.path.join(MXEX_DIR, "日本アクセス_左モーター.mxex")

SYNTHETIC = (
    '<NetIds>'
    '<netid id="400" val="0"><att key="bank" val="1" /></netid>'
    '<netid id="401" val="55"><att key="bank" val="1" /></netid>'
    '</NetIds>'
)


def test_parses_netid_values():
    assert parse_mxex_netids(SYNTHETIC) == {400: 0, 401: 55}


def test_reads_the_real_files():
    values = mxex_netids(RIGHT)
    assert len(values) == 8500


def test_hwto_parameters_are_at_factory_defaults_in_both_motors():
    """実機の mxex は HWTO/ETO 関連が全て初期値だった (2026-08-09 実測)。

    netid 400 = HWTO入力OFF時アラーム発生 (初期値 0 = 無効)
    netid 401 = HWTO-2重系異常検出遅延時間 (初期値 0 = 無効)
    これが「HWTO1 だけを安全リレーで切る片系配線でもアラームが出ない」根拠。
    ここが将来変わったら、Cn4Wiring の既定パラメータも見直すこと。
    """
    for path in (RIGHT, LEFT):
        values = mxex_netids(path)
        assert values[400] == 0
        assert values[401] == 0
        assert values[408] == 0    # ETO解除無効時間 (初期値 0 ms)
        assert values[409] == 1    # ETO解除動作 (ETO-CLR入力) 初期値 1 = ONエッジ
