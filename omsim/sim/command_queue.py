"""CAN 受信スレッドからシミュレーションループへ書込みを渡すキュー。

python-can の Notifier は専用スレッドでコールバックを呼ぶため、SDO の
書込みをその場で DriverModel に適用すると step() と競合する。実機の
ドライバは受信したコマンドを次の制御周期の先頭で適用するので、同じ形に
そろえる（仕様的にも正しく、競合も消える）。

読み出しはキューを通さない。副作用が無く、1ms 待たせると SDO の
タイムアウトを招くため。
"""
import collections
import threading

QueuedWrite = collections.namedtuple("QueuedWrite", ["index", "sub", "value"])


class CommandQueue(object):
    def __init__(self):
        self._lock = threading.Lock()
        self._items = collections.deque()

    def put(self, index, sub, value):
        with self._lock:
            self._items.append(QueuedWrite(index, sub, value))

    def pending_count(self):
        with self._lock:
            return len(self._items)

    def drain(self, model):
        """溜まった書込みを順に適用し、発生した例外の一覧を返す。

        1 件が失敗しても後続を捨てない。捨てると「マスタは書けたつもり
        なのにシミュレータが受け取っていない」という追跡困難な状態になる。
        """
        with self._lock:
            items = list(self._items)
            self._items.clear()

        errors = []
        for item in items:
            try:
                model.write_object(item.index, item.sub, item.value)
            except Exception as err:
                errors.append((item, err))
        return errors
