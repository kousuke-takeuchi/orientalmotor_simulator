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


def test_waveforms_are_drawn_on_a_single_canvas():
    """波形は 1 枚のグラフにまとめる。"""
    html = _read("index.html")
    assert 'id="chart"' in html
    assert html.count("<canvas") == 1
    js = _read("app.js")
    assert "visibleTraces" in js
    assert "renderChart" in js


def test_each_waveform_has_a_checkbox():
    """系列ごとにチェックボックスで表示を切り替えられる。"""
    html = _read("index.html")
    assert 'id="chart-toggles"' in html
    js = _read("app.js")
    assert "renderChartToggles" in js
    assert 'box.type = "checkbox"' in js
    assert "chartVisible" in js
    # チェックを外したら再描画すること
    assert "chartVisible[key] = event.target.checked" in js


def test_legend_shows_the_current_value_and_range():
    """系列ごとに自動スケールするので、凡例に現在値と範囲を出す。"""
    js = _read("app.js")
    assert "renderChartLegend" in js
    assert "現在 " in js
    assert "範囲 " in js


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


def test_motor3d_uses_the_real_step_derived_meshes():
    """近似形状ではなく docs/oriental_motor/ の STEP から起こした実物を使う。"""
    js = _read("motor3d.js")
    assert "/static/models/A1861_F.stl" in js
    assert "/static/models/A1806.stl" in js
    for name in ("A1861_F.stl", "A1806.stl"):
        path = os.path.join(STATIC_DIR, "models", name)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 100000
    # STL ローダも同梱していること (CDN を使わない)
    assert os.path.exists(os.path.join(STATIC_DIR, "vendor", "STLLoader.js"))
    loader = _read(os.path.join("vendor", "STLLoader.js"))
    assert "from './three.module.min.js'" in loader


def test_motor3d_reports_a_model_that_cannot_be_loaded():
    """読めなかったときに黙って近似形状で代替しないこと。"""
    js = _read("motor3d.js")
    assert "console.error" in js
    assert "3D モデルを読み込めません" in js


def test_motor3d_top_level_vars_do_not_collide_with_window_globals():
    js = _read("motor3d.js")
    top_level_var_names = re.findall(r"(?m)^var\s+([A-Za-z_$][\w$]*)", js)
    collisions = sorted(set(top_level_var_names) & DANGEROUS_WINDOW_GLOBALS)
    assert not collisions, (
        "motor3d.js のトップレベル var が window の標準プロパティと衝突しています: "
        "{}".format(collisions))


def test_app_js_knows_the_mode_specific_statusword_bits():
    """bit12/13/15 は運転モードで意味が変わる。pv の名前を pp/hm に出さない。"""
    js = _read("app.js")
    assert "MODE_SPECIFIC_BITS" in js
    for name in ("Set point acknowledge (pp)", "Homing attained (hm)",
                 "Following error (pp)", "Homing error (hm)", "Speed is 0 (pv)"):
        assert name in js
    # モード別の表を通さずに固定表を描いていないこと
    assert "statuswordBits(snap.mode)" in js


def test_index_has_the_alarm_and_io_panes():
    html = _read("index.html")
    assert 'id="pane-alarm"' in html
    assert 'id="pane-io"' in html


def test_app_js_knows_the_remote_io_default_functions():
    js = _read("app.js")
    for name in ("S-ON", "QSTOP", "ALM-RST", "D-SEL7",
                 "SON-MON", "ALM-A", "MOVE", "TLC"):
        assert name in js
    assert "renderAlarms" in js
    assert "renderIo" in js


def test_index_has_a_hidden_replay_pane():
    """再生ペインは --replay のときだけ出す (通常運転では隠す)。"""
    html = _read("index.html")
    assert 'id="pane-replay"' in html
    assert "hidden" in html
    js = _read("app.js")
    assert "/api/replay" in js
    assert "updateReplayFromPayload" in js


def test_app_js_only_asks_for_wiring_in_normal_mode():
    """再生モードでは /api/wiring を投げない (409 がコンソールに残るため)。

    通常運転だと分かってから 1 回だけ取りに行き、失敗時はパネルを隠す。
    """
    js = _read("app.js")
    assert "loadWiringOnce" in js
    assert "wiringRequested" in js
    assert "response.ok" in js
    assert 'getElementById("pane-hwto").hidden = true' in js


def test_traces_of_the_same_unit_share_one_scale():
    """同じ単位の系列は共通スケールにする。

    トレースごとに正規化すると、一定値の速度が 2 本あったときに両方とも
    中央の直線になって重なり、100 r/min と 50 r/min を見分けられない。
    """
    js = _read("app.js")
    assert "scales[trace.seriesKey]" in js
    assert "seriesKey: series.key" in js
