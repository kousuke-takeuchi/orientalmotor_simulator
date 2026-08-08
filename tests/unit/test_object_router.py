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
