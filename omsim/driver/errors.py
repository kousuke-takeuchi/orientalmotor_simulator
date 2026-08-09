"""driver 層の例外。canopen に依存しないため abort コードを整数で持つ。"""

ABORT_NOT_IN_OD = 0x06020000
ABORT_NOT_READABLE = 0x06010001
ABORT_NOT_WRITABLE = 0x06010002
ABORT_VALUE_RANGE = 0x06090030
ABORT_DEVICE_STATE = 0x08000022
# CiA301: 「アプリケーションにデータが無い」。1003h のまだ記録されていない
# sub-index を読んだ場合など。
ABORT_NO_DATA = 0x08000024


class ObjectAccessError(Exception):
    def __init__(self, abort_code, message=""):
        super(ObjectAccessError, self).__init__(
            message or "SDO abort 0x{:08X}".format(abort_code)
        )
        self.abort_code = abort_code


class NotImplementedObjectError(ObjectAccessError):
    """未実装のオブジェクト/値へのアクセス。

    ObjectAccessError のサブクラスなので od_bridge.py の
    ObjectAccessError -> canopen.SdoAbortedError の変換対象に自動的に
    含まれる（生の NotImplementedError は変換対象外で、canopen 側の
    汎用 abort に潰れてメッセージが消えてしまう）。
    """

    def __init__(self, abort_code=ABORT_DEVICE_STATE, message=""):
        super(NotImplementedObjectError, self).__init__(abort_code, message)
