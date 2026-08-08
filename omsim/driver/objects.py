"""オブジェクトインデックスから DriverModel のメソッドへの振り分け表。"""
from omsim.driver.errors import ABORT_NOT_WRITABLE, ObjectAccessError


class ObjectRouter(object):
    def __init__(self):
        self._readers = {}
        self._writers = {}
        # (index, sub) -> 理由の文字列。未実装だが SDO を壊さないための
        # スタブハンドラとして登録されたオブジェクトの一覧。
        self._stubs = {}

    def reader(self, index, sub=0, stub=None):
        def decorate(func):
            self._readers[(index, sub)] = func
            if stub is not None:
                self._stubs[(index, sub)] = stub
            return func

        return decorate

    def writer(self, index, sub=0, stub=None):
        def decorate(func):
            self._writers[(index, sub)] = func
            if stub is not None:
                self._stubs[(index, sub)] = stub
            return func

        return decorate

    def mark_stub(self, index, sub, reason):
        """reader/writer を伴わない項目をスタブとして登録する。

        NMT reset のように OD の read/write を経由しない機能でも、
        「まだ嘘」であることを --list-stubs で機械的に確認できるようにする。
        """
        self._stubs[(index, sub)] = reason

    def has_reader(self, index, sub=0):
        return (index, sub) in self._readers

    def has_writer(self, index, sub=0):
        return (index, sub) in self._writers

    def stubs(self):
        """[(index, sub, 理由), ...] を index, sub 順で返す。"""
        return sorted(
            (index, sub, reason)
            for (index, sub), reason in self._stubs.items()
        )

    def read(self, owner, index, sub):
        func = self._readers.get((index, sub))
        if func is None:
            return None
        return func(owner, sub)

    def write(self, owner, index, sub, value):
        func = self._writers.get((index, sub))
        if func is None:
            raise ObjectAccessError(ABORT_NOT_WRITABLE)
        func(owner, sub, value)
