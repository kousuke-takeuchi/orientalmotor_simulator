from omsim.sim.clock import SimClock
from omsim.sim.recorder import Recorder, attach_recorder


class FakeMessage(object):
    def __init__(self, arbitration_id, data):
        self.arbitration_id = arbitration_id
        self.data = data
        self.is_error_frame = False


class FakeNetwork(object):
    def __init__(self):
        self.listeners = []


def test_attaches_a_listener_to_the_network():
    network = FakeNetwork()
    recorder = Recorder(None)
    attach_recorder(network, recorder, SimClock(realtime=False))
    assert len(network.listeners) == 1
    recorder.close()


def test_received_frames_land_in_the_recorder():
    network = FakeNetwork()
    recorder = Recorder(None)
    attach_recorder(network, recorder, SimClock(realtime=False))
    listener = network.listeners[0]
    listener.on_message_received(
        FakeMessage(0x601, bytes([0x40, 0x41, 0x60, 0x00, 0, 0, 0, 0]))
    )
    frames = recorder.recent_frames()
    assert len(frames) == 1
    assert frames[0]["can_id"] == 0x601
    assert frames[0]["text"] == "SDO rd node1 6041h:00"
    recorder.close()


def test_frame_timestamp_comes_from_the_sim_clock():
    network = FakeNetwork()
    recorder = Recorder(None)
    clock = SimClock(realtime=False)
    attach_recorder(network, recorder, clock)
    clock.advance_for(0.5)
    network.listeners[0].on_message_received(FakeMessage(0x181, bytes([1])))
    assert abs(recorder.recent_frames()[0]["t"] - 0.5) < 1e-9
    recorder.close()


def test_error_frames_are_ignored():
    network = FakeNetwork()
    recorder = Recorder(None)
    attach_recorder(network, recorder, SimClock(realtime=False))
    message = FakeMessage(0x601, bytes(8))
    message.is_error_frame = True
    network.listeners[0].on_message_received(message)
    assert recorder.recent_frames() == []
    recorder.close()
