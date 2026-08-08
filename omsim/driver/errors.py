"""driver 層の例外。canopen に依存しないため abort コードを整数で持つ。"""

ABORT_NOT_IN_OD = 0x06020000
ABORT_NOT_READABLE = 0x06010001
ABORT_NOT_WRITABLE = 0x06010002
ABORT_VALUE_RANGE = 0x06090030
ABORT_DEVICE_STATE = 0x08000022


class ObjectAccessError(Exception):
    def __init__(self, abort_code, message=""):
        super(ObjectAccessError, self).__init__(
            message or "SDO abort 0x{:08X}".format(abort_code)
        )
        self.abort_code = abort_code
