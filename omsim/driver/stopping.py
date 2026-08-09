"""停止動作と option code の解釈。can / canopen を import しないこと。

pp / tq / hm はどれも「どう止まるか」を option code で切り替える。同じ分岐を
モードごとに書き散らさないよう、コード値 -> 停止動作の対応をここへ集約する。

参照 (HP-5143E Object Dictionary 実測):
  605Ah Quick stop option code        -3..6 (既定 2)
  605Bh Shutdown option code           0..1 (既定 0)
  605Ch Disable operation option code  0..1 (既定 1)
  605Dh Halt option code               0..1 (既定 1。0 は予約)
  605Eh Fault reaction option code     0..2 (既定 2)
"""
import collections

from omsim.driver.errors import ABORT_VALUE_RANGE, ObjectAccessError

# 停止のしかた
IMMEDIATE = "immediate"                # 即時停止
SLOW_DOWN = "slow_down"                # slow down ramp (モードの減速度)
QUICK_STOP_RAMP = "quick_stop_ramp"    # 6085h Quick stop deceleration
CUSTOM_RATE = "custom_rate"            # 4735h Custom stopping rate
CUSTOM_TIME = "custom_time"            # 4736h Custom stopping time

StopAction = collections.namedtuple(
    "StopAction", ["kind", "stay_in_state", "non_excitation"])
StopAction.__new__.__defaults__ = (False, False)


_QUICK_STOP = {
    -3: StopAction(CUSTOM_TIME, stay_in_state=True),
    -2: StopAction(CUSTOM_RATE, stay_in_state=True),
    -1: StopAction(IMMEDIATE, stay_in_state=True),
    0: StopAction(IMMEDIATE, stay_in_state=False),
    1: StopAction(SLOW_DOWN, stay_in_state=False),
    2: StopAction(QUICK_STOP_RAMP, stay_in_state=False),
    5: StopAction(SLOW_DOWN, stay_in_state=True),
    6: StopAction(QUICK_STOP_RAMP, stay_in_state=True),
}

_SHUTDOWN = {0: StopAction(IMMEDIATE), 1: StopAction(SLOW_DOWN)}
_DISABLE_OPERATION = {0: StopAction(IMMEDIATE), 1: StopAction(SLOW_DOWN)}
# 605Dh の 0 は仕様上 "Reserved"。設定できてしまうと「予約値なのに何か動く」
# という嘘になるので拒否する。
_HALT = {1: StopAction(SLOW_DOWN)}
_FAULT_REACTION = {
    0: StopAction(IMMEDIATE, non_excitation=True),
    1: StopAction(SLOW_DOWN),
    2: StopAction(QUICK_STOP_RAMP),
}


def _resolve(table, code, index_name):
    code = int(code)
    if code not in table:
        raise ObjectAccessError(
            ABORT_VALUE_RANGE,
            "{} に {} は設定できません (対応値: {})".format(
                index_name, code, ", ".join(str(k) for k in sorted(table))))
    return table[code]


def resolve_quick_stop(code):
    return _resolve(_QUICK_STOP, code, "605Ah")


def resolve_shutdown(code):
    return _resolve(_SHUTDOWN, code, "605Bh")


def resolve_disable_operation(code):
    return _resolve(_DISABLE_OPERATION, code, "605Ch")


def resolve_halt(code):
    return _resolve(_HALT, code, "605Dh")


def resolve_fault_reaction(code):
    return _resolve(_FAULT_REACTION, code, "605Eh")
