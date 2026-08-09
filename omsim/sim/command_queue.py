"""CAN 受信スレッドからシミュレーションループへ書込みを渡すキュー。

python-can の Notifier は専用スレッドでコールバックを呼ぶため、SDO/PDO の
書込みをその場で DriverModel に適用すると step() と競合する。実機の
ドライバは受信したコマンドを次の制御周期の先頭で適用するので、同じ形に
そろえる。

PDO では生産者 (CAN 受信スレッド) が消費者 (1kHz の step()) を追い越し
うる。実機は同じオブジェクトへの複数回書込みは最後の値だけが効くため、
(index, sub) ごとの last-write-wins で保持する。無制限に溜め続けると
遅延が蓄積するため、上限を超えたら最も古い書込み (異なるキー) を破棄し
warning ログを出す (黙って捨てない)。

読み出しはキューを通さない。副作用が無く、1ms 待たせると SDO の
タイムアウトを招くため。
"""
import collections
import logging
import threading

logger = logging.getLogger(__name__)

QueuedWrite = collections.namedtuple(
    "QueuedWrite", ["index", "sub", "value", "trigger"])

# 「同じオブジェクトへの複数回書込みは最後だけが効く」が成り立たない
# オブジェクト。値そのものではなく "遷移" を指示するコマンドレジスタで、
# 潰すと中間状態が失われる。
SEQUENCE_SENSITIVE_OBJECTS = frozenset([
    (0x6040, 0),  # Controlword (CiA402 の状態遷移)
])

DEFAULT_MAXLEN = 64


class CommandQueue(object):
    def __init__(self, maxlen=DEFAULT_MAXLEN):
        self._lock = threading.Lock()
        self._maxlen = maxlen
        # キー -> QueuedWrite。挿入順は OrderedDict のキー順で保つ
        # (異なるキー間の適用順序を保存するため)。同じキーへの再書込みは
        # 一度削除してから append し直し、最新の書込みを最後尾に置く。
        self._items = collections.OrderedDict()
        # 状態遷移コマンド用の連番。同じ (index, sub) でも別キーになるよう
        # 付ける (順序を保って全件残すため)。
        self._sequence = 0

    def _make_key(self, index, sub, value):
        """この書込みをどのキーで保持するかを決める。

        通常のオブジェクトは (index, sub) をキーにして last-write-wins。
        Controlword のような状態遷移コマンドは、値が変わるたびに 1 つの
        遷移を意味するため潰してはならない (6 -> 7 -> F が 1ms 内に重なると
        F だけが残り、中間の遷移が失われてノードが永久に起動しない)。
        同じ値の連投は遷移を生まないので従来どおり 1 件に潰す。
        """
        key = (index, sub)
        if key not in SEQUENCE_SENSITIVE_OBJECTS:
            return key, True
        for existing_key in reversed(self._items):
            existing = self._items[existing_key]
            if (existing.index, existing.sub) == key:
                if existing.value == value:
                    return existing_key, True  # 同値の連投は潰す
                break
        self._sequence += 1
        return (index, sub, self._sequence), False

    def put(self, index, sub, value, trigger="immediate"):
        with self._lock:
            key, coalescing = self._make_key(index, sub, value)
            if coalescing and key in self._items:
                del self._items[key]
            elif len(self._items) >= self._maxlen:
                oldest_key, oldest = next(iter(self._items.items()))
                del self._items[oldest_key]
                logger.warning(
                    "CommandQueue が上限 %d 件を超えたため、最古の書込み "
                    "%04Xh:%02X=%s を破棄しました",
                    self._maxlen, oldest.index, oldest.sub, oldest.value,
                )
            self._items[key] = QueuedWrite(index, sub, value, trigger)

    def pending_count(self):
        with self._lock:
            return len(self._items)

    def drain(self, model, sync_received=False):
        """溜まった書込みのうち、今回適用すべきものだけを取り出して適用する。

        trigger="immediate" は毎回適用する。trigger="sync" は
        sync_received=True の回だけ適用し、そうでなければキューに残して
        次の SYNC まで待つ。

        1 件が失敗しても後続を捨てない。捨てると「マスタは書けたつもり
        なのにシミュレータが受け取っていない」という追跡困難な状態になる。
        """
        with self._lock:
            ready = []
            remaining = collections.OrderedDict()
            for key, item in self._items.items():
                if item.trigger == "sync" and not sync_received:
                    remaining[key] = item
                else:
                    ready.append(item)
            self._items = remaining

        errors = []
        for item in ready:
            try:
                model.write_object(item.index, item.sub, item.value)
            except Exception as err:
                errors.append((item, err))
        return errors
