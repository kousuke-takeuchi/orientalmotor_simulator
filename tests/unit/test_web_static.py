import os
import re

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


# ブラウザの window が持つ標準プロパティ。トップレベルの `var` でこれらと
# 同名の変数を宣言すると、ブラウザでは「window.<name> に代入」になる。
# 読み取り専用の getter しか持たないもの (history など) だと、代入時に
# TypeError が飛んで app.js の実行がそこで止まる。
DANGEROUS_WINDOW_GLOBALS = frozenset(
    [
        "name",
        "status",
        "length",
        "top",
        "parent",
        "self",
        "closed",
        "origin",
        "location",
        "frames",
        "screen",
        "history",
        "navigator",
        "document",
        "window",
    ]
)


def test_app_js_top_level_vars_do_not_collide_with_window_globals():
    js = _read("app.js")
    top_level_var_names = re.findall(r"(?m)^var\s+([A-Za-z_$][\w$]*)", js)
    assert top_level_var_names, "app.js からトップレベルの var 宣言が見つかりませんでした"

    collisions = sorted(
        set(top_level_var_names) & DANGEROUS_WINDOW_GLOBALS
    )
    assert not collisions, (
        "app.js のトップレベル var が window の標準プロパティと衝突しています: "
        "{}  (実ブラウザでは代入時に TypeError が発生し app.js の実行が止まります)".format(
            collisions
        )
    )


# --- 3D ペイン (P3.5) ---

def test_index_has_the_3d_pane_and_loads_motor3d():
    html = _read("index.html")
    assert 'id="pane-3d"' in html
    assert "motor3d.js" in html


def test_three_js_is_vendored_locally():
    """CDN は使わない (オフライン前提)。同梱物とライセンス・版の記録を必須にする。"""
    path = os.path.join(STATIC_DIR, "vendor", "three.module.min.js")
    assert os.path.exists(path)
    assert os.path.getsize(path) > 100000
    readme = _read(os.path.join("vendor", "README.md"))
    assert "0.169.0" in readme
    assert os.path.exists(os.path.join(STATIC_DIR, "vendor", "THREE-LICENSE.txt"))


def test_motor3d_does_not_reference_any_external_host():
    js = _read("motor3d.js")
    assert "http://" not in js
    assert "https://" not in js
    assert "./vendor/three.module.min.js" in js


def test_motor3d_top_level_vars_do_not_collide_with_window_globals():
    js = _read("motor3d.js")
    top_level_var_names = re.findall(r"(?m)^var\s+([A-Za-z_$][\w$]*)", js)
    collisions = sorted(set(top_level_var_names) & DANGEROUS_WINDOW_GLOBALS)
    assert not collisions, (
        "motor3d.js のトップレベル var が window の標準プロパティと衝突しています: "
        "{}".format(collisions))
