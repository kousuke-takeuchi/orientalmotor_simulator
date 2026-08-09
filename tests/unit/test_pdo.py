from omsim.driver.pdo import (
    COB_ID_MASK,
    PDO_RTR_BIT,
    PDO_VALID_BIT,
    PdoCommParams,
    is_reserved_tpdo_transmission_type,
    is_supported_tpdo_transmission_type,
)


def test_valid_pdo_encodes_bit31_clear():
    params = PdoCommParams(cob_id=0x201, valid=True, rtr_allowed=True)
    assert params.encode_cob_id_sub1() & PDO_VALID_BIT == 0


def test_invalid_pdo_encodes_bit31_set():
    params = PdoCommParams(cob_id=0x201, valid=False, rtr_allowed=True)
    assert params.encode_cob_id_sub1() & PDO_VALID_BIT == PDO_VALID_BIT


def test_rtr_not_allowed_encodes_bit30_set():
    params = PdoCommParams(cob_id=0x181, valid=True, rtr_allowed=False)
    assert params.encode_cob_id_sub1() & PDO_RTR_BIT == PDO_RTR_BIT


def test_rtr_allowed_encodes_bit30_clear():
    params = PdoCommParams(cob_id=0x181, valid=True, rtr_allowed=True)
    assert params.encode_cob_id_sub1() & PDO_RTR_BIT == 0


def test_cob_id_round_trips_through_encode_decode():
    params = PdoCommParams(cob_id=0x301, valid=True, rtr_allowed=False)
    raw = params.encode_cob_id_sub1()
    decoded = PdoCommParams.decode_cob_id_sub1(raw)
    assert decoded == {"cob_id": 0x301, "rtr_allowed": False, "valid": True}


def test_cob_id_mask_is_11_bits():
    assert COB_ID_MASK == 0x7FF


def test_reserved_tpdo_transmission_types():
    for value in (0xF1, 0xF5, 0xFB):
        assert is_reserved_tpdo_transmission_type(value) is True
    for value in (0x00, 0xF0, 0xFC, 0xFF):
        assert is_reserved_tpdo_transmission_type(value) is False


def test_supported_tpdo_transmission_types():
    for value in (0x00, 0x01, 0xF0, 0xFC, 0xFD, 0xFE, 0xFF):
        assert is_supported_tpdo_transmission_type(value) is True
    for value in (0xF1, 0xFB):
        assert is_supported_tpdo_transmission_type(value) is False
