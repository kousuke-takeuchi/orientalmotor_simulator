"""ストアードデータ運転の運転データ。can / canopen を import しないこと。

1 件 = 運転方式 / 位置 / 速度 / 加速レート / 減速レート / トルク制限値
(HP-5141J 5-2「データの設定」)。運転方式の値はダイレクトデータ運転と同じ表
(omsim/driver/operation_type.py) を使う。

実機の運転データ R/W コマンドは Modbus / netid の空間にあり、CANopen (SDO)
からは触れない。ここは model の API と mxex から設定する口として持つ。
"""
import collections

# 実機の運転データは 256 件。まず 64 件で実装する (上限は定数で持つ)。
DEFAULT_TABLE_SIZE = 64

OperationData = collections.namedtuple(
    "OperationData",
    ["operation_type", "position", "velocity", "acceleration", "deceleration",
     "torque_limit"])
OperationData.__new__.__defaults__ = (0, 0, 0, 1000, 1000, 10000)


class OperationDataTable(object):
    def __init__(self, size=DEFAULT_TABLE_SIZE):
        self.size = size
        self._entries = [OperationData() for _ in range(size)]

    def __getitem__(self, number):
        number = int(number)
        if not (0 <= number < self.size):
            raise IndexError(
                "運転データ No. {} は範囲外です (0-{})".format(number, self.size - 1))
        return self._entries[number]

    def set(self, number, data):
        number = int(number)
        if not (0 <= number < self.size):
            raise IndexError(
                "運転データ No. {} は範囲外です (0-{})".format(number, self.size - 1))
        self._entries[number] = data
