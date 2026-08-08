import pytest

from omsim.driver.errors import ABORT_NOT_WRITABLE, ObjectAccessError
from omsim.driver.objects import ObjectRouter


class Fake(object):
    router = ObjectRouter()

    def __init__(self):
        self.stored = 7

    @router.reader(0x6041)
    def _read_status(self, sub):
        return self.stored

    @router.writer(0x6040)
    def _write_control(self, sub, value):
        self.stored = value


def test_read_dispatches_to_owner_instance():
    a, b = Fake(), Fake()
    b.stored = 99
    assert Fake.router.read(a, 0x6041, 0) == 7
    assert Fake.router.read(b, 0x6041, 0) == 99


def test_unregistered_read_returns_none():
    assert Fake.router.read(Fake(), 0x1008, 0) is None


def test_write_dispatches_and_isolates_instances():
    a, b = Fake(), Fake()
    Fake.router.write(a, 0x6040, 0, 15)
    assert a.stored == 15
    assert b.stored == 7


def test_unregistered_write_aborts_as_not_writable():
    with pytest.raises(ObjectAccessError) as exc:
        Fake.router.write(Fake(), 0x1008, 0, 1)
    assert exc.value.abort_code == ABORT_NOT_WRITABLE


def test_subindex_is_part_of_the_key():
    assert Fake.router.has_reader(0x6041, 0) is True
    assert Fake.router.has_reader(0x6041, 1) is False


class FakeWithStub(object):
    router = ObjectRouter()

    def __init__(self):
        self.value = 0

    @router.reader(0x409B, stub="理由: 未実装")
    def _read_stub(self, sub):
        return self.value

    @router.writer(0x1016, 1, stub="理由: 未実装2")
    def _write_stub(self, sub, value):
        self.value = value

    @router.reader(0x1008)
    def _read_normal(self, sub):
        return "normal"


def test_stubs_lists_registered_stub_handlers_with_reason():
    stubs = FakeWithStub.router.stubs()
    assert (0x409B, 0, "理由: 未実装") in stubs
    assert (0x1016, 1, "理由: 未実装2") in stubs


def test_stubs_does_not_include_non_stub_handlers():
    keys = set((index, sub) for index, sub, _reason in FakeWithStub.router.stubs())
    assert (0x1008, 0) not in keys
