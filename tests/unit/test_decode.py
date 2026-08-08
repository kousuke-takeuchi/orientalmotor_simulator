from omsim.sim.decode import describe_frame


def test_decodes_nmt_start():
    assert describe_frame(0x000, bytes([0x01, 0x01])) == "NMT start node1"


def test_decodes_nmt_reset_node():
    assert describe_frame(0x000, bytes([0x81, 0x02])) == "NMT reset-node node2"


def test_decodes_sdo_expedited_download_request():
    data = bytes([0x2B, 0x40, 0x60, 0x00, 0x0F, 0x00, 0x00, 0x00])
    assert describe_frame(0x601, data) == "SDO wr node1 6040h:00 = 000Fh"


def test_decodes_sdo_upload_request():
    data = bytes([0x40, 0x41, 0x60, 0x00, 0x00, 0x00, 0x00, 0x00])
    assert describe_frame(0x601, data) == "SDO rd node1 6041h:00"


def test_decodes_sdo_abort():
    data = bytes([0x80, 0x40, 0x60, 0x00, 0x00, 0x00, 0x02, 0x06])
    assert describe_frame(0x581, data) == "SDO abort node1 6040h:00 code=06020000h"


def test_decodes_heartbeat():
    assert describe_frame(0x701, bytes([0x05])) == "HB node1 OPERATIONAL"


def test_decodes_emcy():
    data = bytes([0x05, 0x73, 0x21, 0x00, 0x00, 0x00, 0x00, 0x00])
    assert describe_frame(0x081, data) == "EMCY node1 code=7305h reg=21h"


def test_decodes_tpdo():
    assert describe_frame(0x181, bytes(range(8))) == "TPDO1 node1 len=8"


def test_decodes_rpdo():
    assert describe_frame(0x201, bytes(range(4))) == "RPDO1 node1 len=4"


def test_decodes_sync():
    assert describe_frame(0x080, b"") == "SYNC"


def test_unknown_id_is_reported_as_raw():
    assert describe_frame(0x123, bytes([0xAA])) == "raw 123h len=1"
