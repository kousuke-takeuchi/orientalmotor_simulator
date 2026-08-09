"""PDO 通信パラメータ・マッピングパラメータのビット表現。

CiA301 のビットフィールド (1400h-1403h/1800h-1803h の COB-ID sub1、
1600h-1603h/1A00h-1A03h のマッピングエントリ) を素の Python 値として
表現する。can/canopen を import しないこと (driver 層)。

参照: HP-5143E 4.7 (PDO, p31-33)、Object Dictionary 1400h/1800h 節
(実測値は P3 計画の「仕様で確認済みの事実」を参照)。
"""
import collections

PDO_VALID_BIT = 1 << 31
PDO_RTR_BIT = 1 << 30
COB_ID_MASK = 0x7FF

# RPDO/TPDO 既定 COB-ID のベース (node_id 加算前)。
RPDO_BASE_COB_ID = (0x200, 0x300, 0x400, 0x500)
TPDO_BASE_COB_ID = (0x180, 0x280, 0x380, 0x480)

RPDO_TRANSMISSION_TYPES = frozenset([0x00, 0xFE, 0xFF])


def is_reserved_tpdo_transmission_type(value):
    return 0xF1 <= value <= 0xFB


def is_supported_tpdo_transmission_type(value):
    if is_reserved_tpdo_transmission_type(value):
        return False
    return 0x00 <= value <= 0xFF


MappingEntry = collections.namedtuple("MappingEntry", ["index", "sub", "length_bits"])


def pack_mapping_entry(index, sub, length_bits):
    return ((index & 0xFFFF) << 16) | ((sub & 0xFF) << 8) | (length_bits & 0xFF)


def unpack_mapping_entry(raw):
    return MappingEntry(
        index=(raw >> 16) & 0xFFFF,
        sub=(raw >> 8) & 0xFF,
        length_bits=raw & 0xFF,
    )


class PdoCommParams(object):
    """1400h-1403h (RPDO) / 1800h-1803h (TPDO) 通信パラメータ 1 本ぶん。"""

    def __init__(self, cob_id, valid=True, rtr_allowed=True, transmission_type=255,
                 inhibit_time_100us=0, event_timer_ms=0):
        self.cob_id = cob_id
        self.valid = valid
        self.rtr_allowed = rtr_allowed
        self.transmission_type = transmission_type
        self.inhibit_time_100us = inhibit_time_100us
        self.event_timer_ms = event_timer_ms

    def encode_cob_id_sub1(self):
        value = self.cob_id & COB_ID_MASK
        if not self.rtr_allowed:
            value |= PDO_RTR_BIT
        if not self.valid:
            value |= PDO_VALID_BIT
        return value

    @classmethod
    def decode_cob_id_sub1(cls, raw):
        return {
            "cob_id": raw & COB_ID_MASK,
            "rtr_allowed": not bool(raw & PDO_RTR_BIT),
            "valid": not bool(raw & PDO_VALID_BIT),
        }


class PdoMappingParams(object):
    """1600h-1603h (RPDO) / 1A00h-1A03h (TPDO) マッピングパラメータ 1 本ぶん。"""

    MAX_ENTRIES = 4

    def __init__(self, entries=None):
        self.entries = list(entries) if entries else []

    @property
    def count(self):
        return len(self.entries)

    def total_bits(self):
        return sum(entry.length_bits for entry in self.entries)
