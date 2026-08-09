"""アラームの発生・解除・履歴と EMCY の発行。

アラーム全コードは HP-5141J 第8章 (p420) から P6 で表に起こす。
このフェーズはしくみだけを作り、代表として過負荷のみ定義する。
"""
import collections

ALARM_OVERLOAD = 0x30
EMCY_OVERLOAD = 0x2310
EMCY_ERROR_RESET = 0x0000
# HP-5143E 4.5 実測: FF53h/81h = HWTO input circuit error、
# FF68h/81h = HWTO input detection Non-excitation
ALARM_HWTO_CIRCUIT = 0x53
ALARM_HWTO_DETECTED = 0x68
EMCY_HWTO_CIRCUIT = 0xFF53
EMCY_HWTO_DETECTED = 0xFF68
ERROR_REGISTER_HWTO = 0x81
# HP-5143E 4.5 (p23): Node guarding error or heartbeat error
EMCY_HEARTBEAT_ERROR = 0x8130


class AlarmModel(object):
    def __init__(self, history_size=10):
        self._history = collections.deque(maxlen=history_size)
        self._pending_emcy = collections.deque()
        self.active_alarm = None
        self.error_code = 0
        self.error_register = 0
        self._cause_cleared = False

    @property
    def is_active(self):
        return self.active_alarm is not None

    @property
    def history(self):
        return list(self._history)

    def set_cause_cleared(self, cleared):
        self._cause_cleared = bool(cleared)

    def raise_alarm(self, alarm_code, emcy_code, error_register=0x01):
        if self.is_active:
            return
        self.active_alarm = alarm_code
        self.error_code = emcy_code
        self.error_register = error_register
        self._cause_cleared = False
        # CiA301 Pre-defined error field: 下位16bit = EMCY error code、
        # 上位16bit = メーカ固有情報。1003h に積むのはこの形式であって、
        # メーカ固有アラームコードそのものではない (P2 最終レビュー指摘)。
        packed = (emcy_code & 0xFFFF) | ((alarm_code & 0xFFFF) << 16)
        self._history.appendleft(packed)
        self._pending_emcy.append((emcy_code, error_register))

    def reset(self):
        if not self.is_active:
            return True
        if not self._cause_cleared:
            return False
        self.active_alarm = None
        self.error_code = 0
        self.error_register = 0
        self._pending_emcy.append((EMCY_ERROR_RESET, 0x00))
        return True

    def clear_history(self):
        self._history.clear()

    def pop_pending_emcy(self):
        if not self._pending_emcy:
            return None
        return self._pending_emcy.popleft()
