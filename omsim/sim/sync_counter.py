"""CAN 受信スレッドから step() 側へ SYNC 受信を伝える。

step() は 1ms ごとに 1 回だけ呼ばれるため、1ms 未満の間隔で複数の
SYNC が届いた場合は 1 回として扱う (現実的な運用で SYNC 周期が 1ms を
下回ることは想定しないため、実害は無い)。
"""
import threading


class SyncCounter(object):
    def __init__(self):
        self._lock = threading.Lock()
        self._pending = 0

    def notify(self):
        with self._lock:
            self._pending += 1

    def take(self):
        """溜まった SYNC 受信回数を返し、0 にリセットする。"""
        with self._lock:
            pending, self._pending = self._pending, 0
        return pending
