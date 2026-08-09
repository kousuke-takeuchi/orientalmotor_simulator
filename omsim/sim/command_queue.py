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

QueuedWrite = collections.namedtuple("QueuedWrite", ["index", "sub", "value"])

DEFAULT_MAXLEN = 64


class CommandQueue(object):
    def __init__(self, maxlen=DEFAULT_MAXLEN):
        self._lock = threading.Lock()
        self._maxlen = maxlen
        # (index, sub) -> QueuedWrite。挿入順は OrderedDict のキー順で保つ
        # (異なるキー間の適用順序を保存するため)。同じキーへの再書込みは
        # 一度削除してから append し直し、最新の書込みを最後尾に置く。
        self._items = collections.OrderedDict()

    def put(self, index, sub, value):
        key = (index, sub)
        with self._lock:
            if key in self._items:
                del self._items[key]
            elif len(self._items) >= self._maxlen:
                oldest_key, oldest = next(iter(self._items.items()))
                del self._items[oldest_key]
                logger.warning(
                    "CommandQueue が上限 %d 件を超えたため、最古の書込み "
                    "%04Xh:%02X=%s を破棄しました",
                    self._maxlen, oldest.index, oldest.sub, oldest.value,
                )
            self._items[key] = QueuedWrite(index, sub, value)

    def pending_count(self):
        with self._lock:
            return len(self._items)

    def drain(self, model):
        """溜まった書込みを順に適用し、発生した例外の一覧を返す。

        1 件が失敗しても後続を捨てない。捨てると「マスタは書けたつもり
        なのにシミュレータが受け取っていない」という追跡困難な状態になる。
        """
        with self._lock:
            items = list(self._items.values())
            self._items.clear()

        errors = []
        for item in items:
            try:
                model.write_object(item.index, item.sub, item.value)
            except Exception as err:
                errors.append((item, err))
        return errors
