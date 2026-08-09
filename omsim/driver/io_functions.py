"""入出力信号の割付 No. 表。can / canopen を import しないこと。

出典: HP-5141J 14「入出力信号割り付け一覧」を pdftotext -layout で実測。
ネットワークから機能を割り付けるときは信号名ではなく割付 No. を使う。

R-IN の機能割付パラメータ (R-IN0 機能選択 = NET-ID 17408 / 4400h ...) は
netid が 0x1000 以上のため **CANopen のメーカ固有領域 (4000h-4FFFh) に
収まらず、EDS にも無い**。SDO では触れず、MEXE02 (mxex) からだけ設定できる。
"""

INPUT_FUNCTIONS = {
    0: "未使用",
    1: "FREE",
    2: "S-ON",
    3: "CLR",
    4: "QSTOP",
    5: "STOP",
    7: "BREAK-ATSQ",
    8: "ALM-RST",
    9: "P-PRESET",
    10: "EL-PRST",
    11: "USR-ALM",
    12: "ETO-CLR",
    13: "LAT-CLR",
    14: "INFO-CLR",
    16: "HMI",
    18: "TRQ-LMT",
    19: "SPD-LMT",
    24: "PLOOP-MODE",
    25: "ATL-EN",
    32: "START",
    33: "SSTART",
    35: "NEXT",
    36: "HOME",
    48: "FW-JOG",
    49: "RV-JOG",
    50: "FW-JOG-H",
    51: "RV-JOG-H",
    52: "FW-JOG-P",
    53: "RV-JOG-P",
    56: "FW-POS",
    57: "RV-POS",
    58: "FW-SPD",
    59: "RV-SPD",
    60: "FW-PSH",
    61: "RV-PSH",
    64: "USR-LAT-IN0",
    65: "USR-LAT-IN1",
    66: "FW-BLK",
    67: "RV-BLK",
    68: "FW-LS",
    69: "RV-LS",
    70: "HOMES",
    71: "SLIT",
}
for _index in range(8):
    INPUT_FUNCTIONS[40 + _index] = "M{}".format(_index)
for _index in range(4):
    INPUT_FUNCTIONS[72 + _index] = "ID-SEL{}".format(_index)
for _index in range(16):
    INPUT_FUNCTIONS[80 + _index] = "D-SEL{}".format(_index)
for _index in range(32):
    INPUT_FUNCTIONS[96 + _index] = "R{}".format(_index)
del _index

# 出力は入力と同じ番号に "_R" が付く形 (HP-5141J 14-2 実測)。
OUTPUT_FUNCTIONS = dict(
    (number, name + "_R") for number, name in INPUT_FUNCTIONS.items() if number)
OUTPUT_FUNCTIONS[128] = "CONST-OFF"

# R-IN0-15 の既定割付 (HP-5143E 60FEh 実測。P5 で実装したビット並びと同じ)。
R_IN_DEFAULTS = (
    2,   # R-IN0  S-ON
    24,  # R-IN1  PLOOP-MODE
    18,  # R-IN2  TRQ-LMT
    3,   # R-IN3  CLR
    4,   # R-IN4  QSTOP
    5,   # R-IN5  STOP
    1,   # R-IN6  FREE
    8,   # R-IN7  ALM-RST
    80, 81, 82, 83, 84, 85, 86, 87,   # R-IN8-15  D-SEL0-7
)

R_IN_SLOTS = len(R_IN_DEFAULTS)


def input_function_name(number):
    number = int(number)
    if number not in INPUT_FUNCTIONS:
        raise ValueError("入力信号の割付 No. {} は一覧にありません".format(number))
    return INPUT_FUNCTIONS[number]


def input_function_number(name):
    for number, function in INPUT_FUNCTIONS.items():
        if function == name:
            return number
    raise ValueError("入力信号 {} は一覧にありません".format(name))
