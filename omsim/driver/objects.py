"""オブジェクトインデックスから DriverModel のメソッドへの振り分け表。"""
from omsim.driver.errors import ABORT_NOT_WRITABLE, ObjectAccessError


class ObjectRouter(object):
    def __init__(self):
        self._readers = {}
        self._writers = {}

    def reader(self, index, sub=0):
        def decorate(func):
            self._readers[(index, sub)] = func
            return func

        return decorate

    def writer(self, index, sub=0):
        def decorate(func):
            self._writers[(index, sub)] = func
            return func

        return decorate

    def has_reader(self, index, sub=0):
        return (index, sub) in self._readers

    def has_writer(self, index, sub=0):
        return (index, sub) in self._writers

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
