"""ダイレクトデータ運転。can / canopen を import しないこと。

「データの書き換えと運転の開始を同時に行なう」モード (HP-5141J 4 章)。
CiA402 の運転モード (6060h) とは独立した、メーカ固有の運転系統。

反映トリガ 4033h の構造 (4-3 実測):
  上位 16bit = ダイレクトデータ運転ライフタイム
  下位 16bit = 反映トリガ
    0        起動しない
    1(2,3)   通常起動 (ユーザー速度単位 / ユーザー加減速単位)
    4-19     単位指定起動 (速度・加減速の単位を変える変種)
    負値     個別項目トリガ (その項目を書いた瞬間に反映)
  どちらかが範囲外なら上位・下位とも反映しない。
  同じ値を書いた場合は起動しない。
  「トリガ自動クリア」パラメータ (初期値: 有効) が有効なら、起動の成否に
  よらず下位 16bit は自動で 0 に戻る。
"""
from omsim.driver.errors import (
    ABORT_VALUE_RANGE,
    NotImplementedObjectError,
    ObjectAccessError,
)
from omsim.driver.operation_type import resolve_operation_type

TRIGGER_NONE = 0
# 1-19 が起動トリガ。1/2/3 は通常起動、4-19 は単位指定起動。
TRIGGER_MIN = 1
TRIGGER_MAX = 19
# 単位指定起動 (4-19) は速度/加減速の単位が変わるため、未実装として明示する。
NORMAL_START_TRIGGERS = (1, 2, 3)


class DirectDataState(object):
    """ダイレクトデータ運転の設定値と、起動待ちのトリガ。"""

    def __init__(self):
        self.data_number = 0        # 402Ch
        self.operation_type = 0     # 402Dh
        self.position = 0           # 402Eh
        self.velocity = 0           # 402Fh
        self.acceleration = 1000    # 4030h
        self.deceleration = 1000    # 4031h
        self.trigger = 0            # 4033h 下位 16bit (自動クリア後は 0)
        self.lifetime = 0           # 4033h 上位 16bit
        self.forwarding_destination = 0   # 4034h
        self.auto_clear_trigger = True
        self._last_trigger = 0
        self._pending_start = None  # 起動待ちの運転方式名

    def write_trigger(self, raw):
        """4033h への書き込み。起動すべきなら運転方式名を保持する。"""
        raw = int(raw)
        if raw < 0:
            raise NotImplementedObjectError(
                ABORT_VALUE_RANGE,
                "4033h の負値 ({}) は個別項目トリガで未実装です".format(raw))
        lifetime = (raw >> 16) & 0xFFFF
        trigger = raw & 0xFFFF
        if trigger != TRIGGER_NONE and not (TRIGGER_MIN <= trigger <= TRIGGER_MAX):
            # 範囲外は上位・下位とも反映しない (HP-5141J 4-3)
            raise ObjectAccessError(
                ABORT_VALUE_RANGE, "4033h の反映トリガ {} は範囲外です".format(trigger))
        if trigger not in (TRIGGER_NONE,) + NORMAL_START_TRIGGERS:
            raise NotImplementedObjectError(
                ABORT_VALUE_RANGE,
                "4033h の反映トリガ {} (単位指定起動) は未実装です".format(trigger))

        self.lifetime = lifetime
        if trigger == TRIGGER_NONE:
            self.trigger = 0
            self._last_trigger = 0
            return
        if trigger == self._last_trigger:
            # 同じ値を書いた場合は起動しない
            self.trigger = 0 if self.auto_clear_trigger else trigger
            return
        self._last_trigger = trigger
        self._pending_start = resolve_operation_type(self.operation_type)
        self.trigger = 0 if self.auto_clear_trigger else trigger

    def take_pending_start(self):
        start, self._pending_start = self._pending_start, None
        return start

    def encoded_trigger(self):
        return ((self.lifetime & 0xFFFF) << 16) | (self.trigger & 0xFFFF)
