"""CiA402 ステートマシン。仕様は HP-5143E 6.1 (p34) / 6.2 (p35)。"""


class State(object):
    NOT_READY = "not-ready-to-switch-on"
    SWITCH_ON_DISABLED = "switch-on-disabled"
    READY_TO_SWITCH_ON = "ready-to-switch-on"
    SWITCHED_ON = "switched-on"
    OPERATION_ENABLED = "operation-enabled"
    QUICK_STOP_ACTIVE = "quick-stop-active"
    FAULT_REACTION_ACTIVE = "fault-reaction-active"
    FAULT = "fault"


# HP-5143E 6.1 (p34): Statusword (6041h) 下位ビットの状態コード (mask, value)。
# bit0=Ready to Switch ON, bit1=Switched ON, bit2=Operation Enabled, bit3=Fault,
# bit5=Quick Stop, bit6=Switch ON Disabled は pdftotext -raw 抽出のビット表
# (6.1, p34) と照合済み。ページ番号・ビット番号の対応は確認できたが、各状態の
# 実際のビット値 (0x00/0x40/0x21/0x23/0x27/0x07/0x0F/0x08) は pdftotext では
# 表の数値セルが崩れて再現できず、目視でのビット表との整合から復元したもの。
_STATE_CODE = {
    State.NOT_READY: (0x4F, 0x00),
    State.SWITCH_ON_DISABLED: (0x4F, 0x40),
    State.READY_TO_SWITCH_ON: (0x6F, 0x21),
    State.SWITCHED_ON: (0x6F, 0x23),
    State.OPERATION_ENABLED: (0x6F, 0x27),
    State.QUICK_STOP_ACTIVE: (0x6F, 0x07),
    State.FAULT_REACTION_ACTIVE: (0x4F, 0x0F),
    State.FAULT: (0x4F, 0x08),
}

# HP-5143E 6.1 (p34) のビット表 (pdftotext -raw 抽出) のビット番号と一致を確認済み。
BIT_VOLTAGE_ENABLED = 4
BIT_WARNING = 7
BIT_REMOTE = 9
BIT_TARGET_REACHED = 10
BIT_INTERNAL_LIMIT = 11


def _command(controlword):
    """HP-5143E 6 (p34) の Controlword コマンド表
    (Fault reset=bit7, Enable operation=bit3, Quick stop=bit2,
    Enable voltage=bit1, Switched on=bit0) のビットマスクは pdftotext -raw
    抽出のコマンド表 (Shutdown/Switch ON/Disable Voltage/Quick Stop/
    Disable Operation/Enable Operation/Fault Reset の各行) と照合済み。
    """
    if controlword & 0x87 == 0x06:
        return "shutdown"
    if controlword & 0x8F == 0x0F:
        return "enable-operation"
    if controlword & 0x8F == 0x07:
        return "switch-on"          # disable-operation と同一ビット列
    if controlword & 0x86 == 0x02:
        return "quick-stop"
    if controlword & 0x82 == 0x00:
        return "disable-voltage"
    return None


class Cia402StateMachine(object):
    def __init__(self):
        self.state = State.NOT_READY
        self.voltage_enabled = True
        self.warning = False
        self.target_reached = False
        self.internal_limit_active = False
        self.remote = True
        self._fault_active = False
        self._controlword = 0x0000

    @property
    def controlword(self):
        return self._controlword

    @property
    def is_operation_enabled(self):
        return self.state == State.OPERATION_ENABLED

    @property
    def statusword(self):
        mask, value = _STATE_CODE[self.state]
        word = value
        if self.voltage_enabled:
            word |= 1 << BIT_VOLTAGE_ENABLED
        if self.warning:
            word |= 1 << BIT_WARNING
        if self.remote:
            word |= 1 << BIT_REMOTE
        if self.target_reached:
            word |= 1 << BIT_TARGET_REACHED
        if self.internal_limit_active:
            word |= 1 << BIT_INTERNAL_LIMIT
        return word

    def set_fault(self, active):
        self._fault_active = active
        if active and self.state not in (State.FAULT, State.FAULT_REACTION_ACTIVE):
            self.state = State.FAULT_REACTION_ACTIVE

    def _auto_transition_from_not_ready(self):
        """HP-5143E 6.2 (p35) Transitions 0-1: 電源投入直後の自動遷移
        (not-ready-to-switch-on -> switch-on-disabled) は Controlword を
        待たない。step() と write_controlword() の両方から呼ばれる共通処理。
        """
        if self.state == State.NOT_READY:
            self.state = State.SWITCH_ON_DISABLED

    def write_controlword(self, value):
        previous = self._controlword
        self._controlword = value
        rising_fault_reset = bool(value & 0x80) and not (previous & 0x80)

        self._auto_transition_from_not_ready()

        if self.state == State.FAULT:
            if rising_fault_reset and not self._fault_active:
                self.state = State.SWITCH_ON_DISABLED
            return
        if self.state == State.FAULT_REACTION_ACTIVE:
            return

        command = _command(value)
        if command == "disable-voltage":
            self.state = State.SWITCH_ON_DISABLED
        elif command == "quick-stop":
            # HP-5143E 6 (p34) コマンド表: Quick Stop は Transitions 7, 10, 11
            # を起こす。6.2 (p35) より
            #   7:  ready-to-switch-on -> switch-on-disabled
            #   10: switched-on -> switch-on-disabled
            #       (Disable Voltage または Quick Stop のいずれでも発生)
            #   11: operation-enabled -> quick-stop-active
            # switch-on-disabled / quick-stop-active 等は Quick Stop の
            # 遷移元として表に無いため状態を変えない。
            # 注: 遷移表では QSTOP 信号入力・HWTO 信号入力でも同じ遷移が
            # 起こるとされているが、これらの信号入力は P5 (CN4 入出力と
            # 動力遮断機能) で実装予定であり、ここでは未対応。
            if self.state == State.OPERATION_ENABLED:
                self.state = State.QUICK_STOP_ACTIVE
            elif self.state == State.READY_TO_SWITCH_ON:
                self.state = State.SWITCH_ON_DISABLED
            elif self.state == State.SWITCHED_ON:
                self.state = State.SWITCH_ON_DISABLED
        elif command == "shutdown":
            if self.state in (
                State.SWITCH_ON_DISABLED, State.SWITCHED_ON, State.OPERATION_ENABLED
            ):
                self.state = State.READY_TO_SWITCH_ON
        elif command == "switch-on":
            if self.state in (State.READY_TO_SWITCH_ON, State.OPERATION_ENABLED):
                self.state = State.SWITCHED_ON
        elif command == "enable-operation":
            if self.state in (State.SWITCHED_ON, State.OPERATION_ENABLED):
                self.state = State.OPERATION_ENABLED

    def step(self, dt):
        if self.state == State.NOT_READY:
            self._auto_transition_from_not_ready()
            return
        if self.state == State.FAULT_REACTION_ACTIVE:
            self.state = State.FAULT
            return
        if not self.voltage_enabled and self.state in (
            State.READY_TO_SWITCH_ON, State.SWITCHED_ON,
            State.OPERATION_ENABLED, State.QUICK_STOP_ACTIVE,
        ):
            self.state = State.SWITCH_ON_DISABLED
