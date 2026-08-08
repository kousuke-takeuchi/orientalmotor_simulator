"""CAN フレームを人間が読める 1 行に変換する。HP-5143E 3.3 (COB-ID) と 4 章に対応。"""
import struct

NMT_COMMANDS = {
    0x01: "start",
    0x02: "stop",
    0x80: "pre-operational",
    0x81: "reset-node",
    0x82: "reset-communication",
}
NMT_STATES = {0x00: "BOOTUP", 0x04: "STOPPED", 0x05: "OPERATIONAL", 0x7F: "PRE-OPERATIONAL"}
TPDO_BASES = (0x180, 0x280, 0x380, 0x480)
RPDO_BASES = (0x200, 0x300, 0x400, 0x500)


def _index_sub(data):
    index = data[1] | (data[2] << 8)
    return index, data[3]


def _sdo_request(node_id, data):
    ccs = data[0] >> 5
    index, sub = _index_sub(data)
    if ccs == 2:  # upload
        return "SDO rd node{} {:04X}h:{:02X}".format(node_id, index, sub)
    if ccs == 1:  # download
        value = struct.unpack("<I", data[4:8])[0]
        return "SDO wr node{} {:04X}h:{:02X} = {:04X}h".format(node_id, index, sub, value)
    if data[0] == 0x80:
        code = struct.unpack("<I", data[4:8])[0]
        return "SDO abort node{} {:04X}h:{:02X} code={:08X}h".format(node_id, index, sub, code)
    return "SDO node{} cmd={:02X}h".format(node_id, data[0])


def _sdo_response(node_id, data):
    if data[0] == 0x80:
        index, sub = _index_sub(data)
        code = struct.unpack("<I", data[4:8])[0]
        return "SDO abort node{} {:04X}h:{:02X} code={:08X}h".format(node_id, index, sub, code)
    scs = data[0] >> 5
    index, sub = _index_sub(data)
    if scs == 2:  # upload response
        value = struct.unpack("<I", data[4:8])[0]
        return "SDO rd-resp node{} {:04X}h:{:02X} = {:04X}h".format(node_id, index, sub, value)
    if scs == 3:  # download response
        return "SDO wr-ack node{} {:04X}h:{:02X}".format(node_id, index, sub)
    return "SDO node{} resp={:02X}h".format(node_id, data[0])


def describe_frame(can_id, data, node_ids=None):
    data = bytes(data)
    if can_id == 0x000 and len(data) >= 2:
        return "NMT {} node{}".format(NMT_COMMANDS.get(data[0], "cmd{:02X}h".format(data[0])), data[1])
    if can_id == 0x080 and not data:
        return "SYNC"
    if 0x081 <= can_id <= 0x0FF and len(data) >= 3:
        code = data[0] | (data[1] << 8)
        return "EMCY node{} code={:04X}h reg={:02X}h".format(can_id - 0x080, code, data[2])
    if 0x701 <= can_id <= 0x77F and len(data) >= 1:
        state = NMT_STATES.get(data[0], "{:02X}h".format(data[0]))
        return "HB node{} {}".format(can_id - 0x700, state)
    if 0x581 <= can_id <= 0x5FF and len(data) == 8:
        return _sdo_response(can_id - 0x580, data)
    if 0x601 <= can_id <= 0x67F and len(data) == 8:
        return _sdo_request(can_id - 0x600, data)
    for number, base in enumerate(TPDO_BASES, start=1):
        if base + 1 <= can_id <= base + 0x7F:
            return "TPDO{} node{} len={}".format(number, can_id - base, len(data))
    for number, base in enumerate(RPDO_BASES, start=1):
        if base + 1 <= can_id <= base + 0x7F:
            return "RPDO{} node{} len={}".format(number, can_id - base, len(data))
    return "raw {:X}h len={}".format(can_id, len(data))
