"""メーカ固有運転の「運転方式」テーブル。can / canopen を import しないこと。

ダイレクトデータ運転 (402Dh) とストアードデータ運転 (運転データ R/W) は
同じ運転方式の値を使う。値の意味が 2 か所に割れないよう、ここへ集約する。

出典: HP-5141J 3-4「運転方式一覧」を pdftotext -layout で実測 (2026-08-09)。
標準モードの設定値のみを扱う (モーション拡張モードの 31/39/48-51 は別軸)。
"""
from omsim.driver.errors import (
    ABORT_VALUE_RANGE,
    NotImplementedObjectError,
    ObjectAccessError,
)

TYPE_DECELERATION_STOP = 0        # 減速停止 (指定した運転プロファイルに従う)
TYPE_ABSOLUTE = 1                 # 絶対位置決め
TYPE_RELATIVE_COMMAND = 2         # 相対位置決め (指令位置基準)
TYPE_RELATIVE_DETECTED = 3        # 相対位置決め (検出位置基準)
TYPE_CONTINUOUS_VELOCITY = 16     # 連続運転 (速度制御)
TYPE_IMMEDIATE_STOP = 32          # 即停止

# 値 -> (実装名 or None, 説明)。None は「表にはあるがこのフェーズでは未実装」。
OPERATION_TYPES = {
    0: ("deceleration_stop", "減速停止 (指定した運転プロファイルに従う)"),
    1: ("absolute", "絶対位置決め"),
    2: ("relative_command", "相対位置決め (指令位置基準)"),
    3: ("relative_detected", "相対位置決め (検出位置基準)"),
    4: (None, "相対位置決め (目標位置基準)"),
    5: (None, "相対位置決め速度制御 (指令位置基準)"),
    6: (None, "相対位置決め速度制御 (検出位置基準)"),
    7: (None, "連続運転 (位置制御)"),
    8: (None, "WRAP 絶対位置決め"),
    9: (None, "WRAP 近回り位置決め"),
    10: (None, "WRAP-FWD 方向絶対位置決め"),
    11: (None, "WRAP-RVS 方向絶対位置決め"),
    12: (None, "WRAP 絶対押し当て"),
    13: (None, "WRAP 近回り押し当て"),
    14: (None, "WRAP-FWD 方向押し当て"),
    15: (None, "WRAP-RVS 方向押し当て"),
    16: ("continuous_velocity", "連続運転 (速度制御)"),
    17: (None, "連続運転 (押し当て)"),
    18: (None, "連続運転 (トルク制御)"),
    19: (None, "連続運転 (サイクリック速度制御)"),
    20: (None, "絶対位置決め押し当て"),
    21: (None, "相対位置決め押し当て (指令位置基準)"),
    22: (None, "相対位置決め押し当て (検出位置基準)"),
    23: (None, "相対位置決め押し当て (目標位置基準)"),
    31: (None, "減速停止 (動作中の運転プロファイルに従う)"),
    32: ("immediate_stop", "即停止"),
    39: (None, "連続運転 (位置制御) / モーション拡張モード"),
    48: (None, "連続運転 (速度制御) / モーション拡張モード"),
    49: (None, "連続運転 (押し当て) / モーション拡張モード"),
    50: (None, "連続運転 (トルク制御) / モーション拡張モード"),
    51: (None, "連続運転 (サイクリック速度制御) / モーション拡張モード"),
}

SUPPORTED_OPERATION_TYPES = frozenset(
    value for value, (name, _desc) in OPERATION_TYPES.items() if name is not None)


def resolve_operation_type(value):
    """運転方式の値を実装名に変換する。未対応/範囲外は例外。"""
    value = int(value)
    entry = OPERATION_TYPES.get(value)
    if entry is None:
        raise ObjectAccessError(
            ABORT_VALUE_RANGE, "運転方式 {} は仕様の一覧にありません".format(value))
    name, description = entry
    if name is None:
        raise NotImplementedObjectError(
            ABORT_VALUE_RANGE,
            "運転方式 {} ({}) は未実装です".format(value, description))
    return name
