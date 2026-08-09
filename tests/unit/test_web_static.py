import os

STATIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "omsim",
    "web",
    "static",
)


def _read(name):
    with open(os.path.join(STATIC_DIR, name), encoding="utf-8") as handle:
        return handle.read()


def test_index_loads_the_script_and_style():
    html = _read("index.html")
    assert "app.js" in html
    assert "style.css" in html


def test_index_has_the_three_panes():
    html = _read("index.html")
    for pane_id in ("pane-status", "pane-waveform", "pane-canlog"):
        assert 'id="{}"'.format(pane_id) in html


def test_app_js_connects_to_the_websocket():
    js = _read("app.js")
    assert "/ws" in js
    assert "WebSocket" in js


def test_app_js_knows_every_statusword_bit_name():
    js = _read("app.js")
    for name in (
        "Ready to switch on",
        "Switched on",
        "Operation enabled",
        "Fault",
        "Voltage enabled",
        "Quick stop",
        "Switch on disabled",
        "Warning",
        "Remote",
        "Target reached",
        "Internal limit active",
    ):
        assert name in js


def test_app_js_renders_the_monitor_values():
    js = _read("app.js")
    for key in (
        "actual_velocity_rpm",
        "command_velocity_rpm",
        "target_velocity_rpm",
        "actual_position",
        "torque_permille",
        "statusword",
        "state",
        "alarm",
    ):
        assert key in js


def test_app_js_has_a_waveform_buffer_and_canvas_drawing():
    js = _read("app.js")
    assert "HISTORY_POINTS" in js
    assert "getContext" in js
    assert "drawChart" in js


def test_app_js_charts_velocity_position_and_torque():
    js = _read("app.js")
    assert "SERIES" in js
    for key in ("actual_velocity_rpm", "actual_position", "torque_permille"):
        assert key in js


def test_app_js_renders_the_can_log_with_filter_and_pause():
    js = _read("app.js")
    assert "renderCanLog" in js
    assert "filter" in js
    assert "pause" in js


def test_index_notes_the_receive_only_limitation():
    html = _read("index.html")
    assert "受信" in html


def test_app_js_can_log_pause_is_separate_from_the_global_pause_flag():
    js = _read("app.js")
    assert "canlogPaused" in js
    onmessage_start = js.index("socket.onmessage")
    onmessage_body = js[onmessage_start:js.index("};", onmessage_start)]
    assert "state.paused" not in onmessage_body
