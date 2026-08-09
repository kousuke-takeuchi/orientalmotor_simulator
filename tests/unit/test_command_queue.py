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


def test_same_key_keeps_only_the_last_value():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 100)
    queue.put(0x6083, 0, 200)
    assert queue.pending_count() == 1
    queue.drain(model)
    assert model.read_object(0x6083) == 200
    assert queue.pending_count() == 0


def test_different_keys_are_both_applied():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 300)
    queue.put(0x6084, 0, 400)
    assert queue.pending_count() == 2
    queue.drain(model)
    assert model.read_object(0x6083) == 300
    assert model.read_object(0x6084) == 400


def test_drain_on_empty_queue_is_a_no_op():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.drain(model)
    assert queue.pending_count() == 0


def test_drain_reports_errors_without_losing_later_commands():
    """不正な書き込みがあっても後続のコマンドは適用される。"""
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    # last-write-wins なので、同じキーだと後勝ちで 1 件に潰れてしまう。
    # 「先の書込みが失敗しても後続が適用される」ことを見るため別キーにする。
    queue.put(0x6083, 0, 0)      # 0 は範囲外 (1 以上)
    queue.put(0x6084, 0, 500)
    errors = queue.drain(model)
    assert len(errors) == 1
    assert model.read_object(0x6084) == 500


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

    # 全スレッドが同じ (0x6083, 0) に書くため、last-write-wins で 1 件に収束する。
    assert queue.pending_count() == 1
    queue.drain(model)
    assert queue.pending_count() == 0
    assert 1 <= model.read_object(0x6083) <= 200


def test_two_queues_are_independent():
    a, b = CommandQueue(), CommandQueue()
    a.put(0x6083, 0, 1)
    assert b.pending_count() == 0


def test_maxlen_evicts_the_oldest_distinct_key():
    queue = CommandQueue(maxlen=2)
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 100)   # 1 件目
    queue.put(0x6084, 0, 200)   # 2 件目、上限ちょうど
    queue.put(0x605A, 0, 0)     # 3 件目、上限超過 -> 最古 (0x6083) を破棄
    assert queue.pending_count() == 2
    queue.drain(model)
    # 0x6083 への書込みは破棄されたので既定値のまま
    assert model.read_object(0x6083) == 1000
    # 生き残った 2 件は適用される
    assert model.read_object(0x6084) == 200
    assert model.read_object(0x605A) == 0


def test_maxlen_is_not_consumed_by_updates_to_the_same_key():
    queue = CommandQueue(maxlen=2)
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 100)
    queue.put(0x6083, 0, 200)   # 同じキーの更新は新しい枠を消費しない
    queue.put(0x6084, 0, 300)
    assert queue.pending_count() == 2
    queue.drain(model)
    assert model.read_object(0x6083) == 200
    assert model.read_object(0x6084) == 300


def test_immediate_trigger_is_applied_every_drain():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 500, trigger="immediate")
    queue.drain(model, sync_received=False)
    assert model.read_object(0x6083) == 500


def test_sync_trigger_waits_for_sync_received():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 600, trigger="sync")
    queue.drain(model, sync_received=False)
    assert model.read_object(0x6083) == 1000  # まだ既定値のまま
    assert queue.pending_count() == 1

    queue.drain(model, sync_received=True)
    assert model.read_object(0x6083) == 600
    assert queue.pending_count() == 0


def test_sync_and_immediate_can_coexist_in_the_same_drain():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 700, trigger="sync")
    queue.put(0x6084, 0, 800, trigger="immediate")
    queue.drain(model, sync_received=False)
    assert model.read_object(0x6083) == 1000  # sync 待ち
    assert model.read_object(0x6084) == 800   # immediate は即時反映
    assert queue.pending_count() == 1


def test_default_trigger_is_immediate():
    queue = CommandQueue()
    model = DriverModel(node_id=1)
    queue.put(0x6083, 0, 900)  # trigger 省略
    queue.drain(model)         # sync_received 省略
    assert model.read_object(0x6083) == 900
