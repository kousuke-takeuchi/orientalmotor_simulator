"""アラームコードの全表。can / canopen を import しないこと。

出典 (すべて pdftotext -layout で実測):
  HP-5143E 4.5 「Error code and Error register」
    メーカ固有アラームの EMCY コードは 0xFF00 | アラームコード、
    error register は 81h。通信系だけ CiA301 標準コード (error register 11h)。
  HP-5141J 8 章「1-2 アラーム一覧」
    ALM-RST 入力による解除可否と、アラーム時のモーター励磁の扱い。

励磁の扱い:
  "non_excitation"            即座に無励磁
  "non_excitation_after_stop" 減速後に無励磁
"""

ERROR_REGISTER_MANUFACTURER = 0x81
EMCY_MANUFACTURER_BASE = 0xFF00

NON_EXCITATION = "non_excitation"
NON_EXCITATION_AFTER_STOP = "non_excitation_after_stop"

# code -> (名前, ALM-RST で解除できるか, 励磁の扱い)
ALARM_CODES = {
    0x10: ("Position deviation", True, NON_EXCITATION_AFTER_STOP),
    0x20: ("Overcurrent", False, NON_EXCITATION),
    0x21: ("Main circuit overheat", True, NON_EXCITATION_AFTER_STOP),
    0x22: ("Overvoltage", True, NON_EXCITATION),
    0x25: ("Undervoltage", True, NON_EXCITATION_AFTER_STOP),
    0x26: ("Motor overheat", True, NON_EXCITATION_AFTER_STOP),
    0x28: ("Encoder error", False, NON_EXCITATION),
    0x29: ("Internal circuit error", False, NON_EXCITATION),
    0x2A: ("Encoder communication error", False, NON_EXCITATION),
    0x30: ("Overload", True, NON_EXCITATION_AFTER_STOP),
    0x31: ("Overspeed", True, NON_EXCITATION_AFTER_STOP),
    0x41: ("EEPROM error", False, NON_EXCITATION),
    0x42: ("Initial encoder error", False, NON_EXCITATION),
    0x44: ("Encoder EEPROM error", False, NON_EXCITATION),
    0x45: ("Motor combination error", False, NON_EXCITATION),
    0x4A: ("Return-to-home incomplete", True, NON_EXCITATION_AFTER_STOP),
    0x50: ("Electromagnetic brake overcurrent", False, NON_EXCITATION),
    0x53: ("HWTO input circuit error", False, NON_EXCITATION),
    0x55: ("Electromagnetic brake connection error", False, NON_EXCITATION),
    0x60: ("+-LS both sides active", True, NON_EXCITATION_AFTER_STOP),
    0x61: ("Reverse +-LS connection", True, NON_EXCITATION_AFTER_STOP),
    0x62: ("Return-to-home operation error", True, NON_EXCITATION_AFTER_STOP),
    0x63: ("No HOMES", True, NON_EXCITATION_AFTER_STOP),
    0x64: ("Z, SLIT signal error", True, NON_EXCITATION_AFTER_STOP),
    0x66: ("Hardware overtravel", True, NON_EXCITATION_AFTER_STOP),
    0x67: ("Software overtravel", True, NON_EXCITATION_AFTER_STOP),
    0x68: ("HWTO input detection", True, NON_EXCITATION),
    0x6A: ("Return-to-home additional operation error", True,
           NON_EXCITATION_AFTER_STOP),
    0x70: ("Operation data error", True, NON_EXCITATION_AFTER_STOP),
    0x71: ("Unit setting error", True, NON_EXCITATION_AFTER_STOP),
    0x81: ("Network bus error", True, NON_EXCITATION_AFTER_STOP),
    0x84: ("RS-485 communication error", True, NON_EXCITATION_AFTER_STOP),
    0x85: ("RS-485 communication timeout", True, NON_EXCITATION_AFTER_STOP),
    0x8C: ("Outside setting range", True, NON_EXCITATION_AFTER_STOP),
    0xF0: ("CPU error", False, NON_EXCITATION),
    0xF3: ("CPU overload", False, NON_EXCITATION),
}

# 通信系は CiA301 標準の EMCY コード (error register 11h)。
COMMUNICATION_EMCY = {
    "can_overrun": (0x8110, 0x11),
    "can_error_passive": (0x8120, 0x11),
    "node_guarding": (0x8130, 0x11),
    "bus_off_recovered": (0x8140, 0x11),
    "pdo_length": (0x8210, 0x11),
}


def alarm_name(code):
    return ALARM_CODES[int(code)][0]


def is_resettable(code):
    return ALARM_CODES[int(code)][1]


def excitation_behaviour(code):
    return ALARM_CODES[int(code)][2]


def emcy_for(code):
    """メーカ固有アラームの EMCY コード。"""
    return EMCY_MANUFACTURER_BASE | (int(code) & 0xFF)


def error_register_for(code):
    ALARM_CODES[int(code)]   # 未知のコードはここで KeyError
    return ERROR_REGISTER_MANUFACTURER
