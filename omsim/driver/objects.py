"""オブジェクトインデックスから DriverModel のメソッドへの振り分け表。"""
from omsim.driver.errors import (
    ABORT_NOT_IN_OD,
    ABORT_NOT_WRITABLE,
    ObjectAccessError,
)


class ObjectRouter(object):
    def __init__(self):
        self._readers = {}
        self._writers = {}
        # (index, sub) -> 理由の文字列。未実装だが SDO を壊さないための
        # スタブハンドラとして登録されたオブジェクトの一覧。
        self._stubs = {}
        self._passthrough = set()

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

    def passthrough(self, index, sub=0, reason=""):
        """値を保持して読み返せるが、挙動には一切効かないオブジェクトを登録する。

        MEXE02 の .mxex に保存される純パラメータ群のように、「読み書きできる
        こと自体に意味がある」オブジェクトのための口。書かれるまでは None を
        返して EDS の既定値へフォールスルーし、書かれた後はその値を返す。

        挙動に効かない以上これは未実装であり、必ずスタブ一覧にも載せる。
        """
        key = (index, sub)
        self._passthrough.add(key)
        self._readers[key] = _passthrough_reader(key)
        self._writers[key] = _passthrough_writer(key)
        self._stubs[key] = reason

    def implemented_keys(self):
        """reader または writer が登録されている (index, sub) の集合。"""
        return set(self._readers) | set(self._writers)

    def passthrough_keys(self):
        return set(self._passthrough)

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
            raise ObjectAccessError(
                ABORT_NOT_IN_OD,
                "{:04X}h:{:02X} は未実装です (omsim --coverage で一覧)".format(index, sub),
            )
        return func(owner, sub)

    def write(self, owner, index, sub, value):
        func = self._writers.get((index, sub))
        if func is None:
            raise ObjectAccessError(ABORT_NOT_WRITABLE)
        func(owner, sub, value)


def _passthrough_reader(key):
    def read(owner, sub):
        return owner.passthrough_values.get(key)

    return read


def _passthrough_writer(key):
    def write(owner, sub, value):
        owner.passthrough_values[key] = int(value)

    return write
