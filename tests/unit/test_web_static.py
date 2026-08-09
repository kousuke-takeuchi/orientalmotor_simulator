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
