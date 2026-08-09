import threading

from omsim.driver.model import DriverModel
from omsim.sim.command_queue import CommandQueue


def test_starts_empty():
    assert CommandQueue().pending_count() == 0


def test_put_does_not_apply_immediately():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 1234)
    assert model.read_object(0x6083) != 1234
    assert queue.pending_count() == 1


def test_drain_applies_in_order():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 100)
    queue.put(0x6083, 0, 200)
    queue.drain(model)
    assert model.read_object(0x6083) == 200
    assert queue.pending_count() == 0


def test_drain_on_empty_queue_is_a_no_op():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.drain(model)
    assert queue.pending_count() == 0


def test_drain_reports_errors_without_losing_later_commands():
    """不正な書き込みがあっても後続のコマンドは適用される。"""
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 0)      # 0 は範囲外 (1 以上)
    queue.put(0x6083, 0, 500)
    errors = queue.drain(model)
    assert len(errors) == 1
    assert model.read_object(0x6083) == 500


def test_is_safe_across_threads():
    queue = CommandQueue()
    model = DriverModel(node_id=1)

    def producer():
        for value in range(1, 201):
            queue.put(0x6083, 0, value)

    threads = [threading.Thread(target=producer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert queue.pending_count() == 800
    queue.drain(model)
    assert queue.pending_count() == 0


def test_two_queues_are_independent():
    a, b = CommandQueue(), CommandQueue()
    a.put(0x6083, 0, 1)
    assert b.pending_count() == 0
