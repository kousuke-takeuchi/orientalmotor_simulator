"use strict";

// HP-5143E 6.1 (p34) の Statusword ビット割り当て。
// omsim/driver/state_machine.py の実装と一致させること。
var STATUSWORD_BITS = [
  [0, "Ready to switch on"],
  [1, "Switched on"],
  [2, "Operation enabled"],
  [3, "Fault"],
  [4, "Voltage enabled"],
  [5, "Quick stop"],
  [6, "Switch on disabled"],
  [7, "Warning"],
  [9, "Remote"],
  [10, "Target reached"],
  [11, "Internal limit active"]
];

// bit12/13/15 は運転モードで意味が変わる (HP-5143E 7.2.4 / 7.3.4 / 7.4.4 / 7.5.4)。
// モード番号は 6061h の値。
var MODE_SPECIFIC_BITS = {
  1: [[12, "Set point acknowledge (pp)"], [13, "Following error (pp)"], [15, "Torque limit"]],
  3: [[12, "Speed is 0 (pv)"]],
  4: [[15, "Torque limit (tq)"]],
  6: [[12, "Homing attained (hm)"], [13, "Homing error (hm)"], [15, "Torque limit"]]
};

function statuswordBits(mode) {
  return STATUSWORD_BITS.concat(MODE_SPECIFIC_BITS[mode] || []);
}

var state = { canlogPaused: false, filter: "", nodes: {}, frames: [] };

var HISTORY_POINTS = 300;  // 100ms 間隔 x 300 = 30 秒ぶん

var SERIES = [
  { key: "actual_velocity_rpm", label: "速度 [r/min]", color: "#7ee2a8" },
  { key: "actual_position", label: "位置 [inc]", color: "#8ab4ff" },
  { key: "torque_permille", label: "トルク [‰]", color: "#ffcf7e" }
];

var chartHistory = {};  // nodeId -> { key -> [値] }

function pushHistory(nodes) {
  Object.keys(nodes).forEach(function (nodeId) {
    if (!chartHistory[nodeId]) {
      chartHistory[nodeId] = {};
      SERIES.forEach(function (series) { chartHistory[nodeId][series.key] = []; });
    }
    SERIES.forEach(function (series) {
      var buffer = chartHistory[nodeId][series.key];
      buffer.push(Number(nodes[nodeId][series.key]) || 0);
      if (buffer.length > HISTORY_POINTS) buffer.shift();
    });
  });
}

// どの波形を表示するか。キーは "nodeId/系列キー"。
// 既定は速度だけ ON にしておく (全部出すと初見で読めないため)。
var chartVisible = {};

function traceKey(nodeId, seriesKey) {
  return nodeId + "/" + seriesKey;
}

// node ごとに線の濃さを変えて、同じ系列でもノードを見分けられるようにする。
function traceColor(series, nodeIndex) {
  var shades = ["", "88"];   // 2 台目以降は半透明
  return series.color + (shades[nodeIndex % shades.length] || "");
}

function visibleTraces(nodes) {
  var traces = [];
  Object.keys(nodes).sort().forEach(function (nodeId, nodeIndex) {
    SERIES.forEach(function (series) {
      var key = traceKey(nodeId, series.key);
      if (!chartVisible[key]) return;
      traces.push({
        key: key,
        seriesKey: series.key,
        label: "node " + nodeId + " / " + series.label,
        color: traceColor(series, nodeIndex),
        values: (chartHistory[nodeId] || {})[series.key] || []
      });
    });
  });
  return traces;
}

function drawChart(canvas, traces) {
  var ctx = canvas.getContext("2d");
  var width = canvas.width = canvas.clientWidth;
  var height = canvas.height = canvas.clientHeight;
  ctx.clearRect(0, 0, width, height);

  // 中央の基準線 (各系列は自分の min-max で正規化して描くので、0 ではなく
  // 「表示範囲の中央」を示す線)
  ctx.strokeStyle = "#2b313b";
  ctx.beginPath();
  ctx.moveTo(0, height / 2);
  ctx.lineTo(width, height / 2);
  ctx.stroke();

  // スケールは「系列 (単位) ごと」に共通にする。トレースごとに正規化すると、
  // 一定値の速度が 2 本あったときに両方とも中央の直線になって重なり、
  // node 1 の 100 r/min と node 2 の 50 r/min を見分けられなくなる。
  var scales = {};
  traces.forEach(function (trace) {
    if (!trace.values.length) return;
    var scale = scales[trace.seriesKey];
    var low = Math.min.apply(null, trace.values);
    var high = Math.max.apply(null, trace.values);
    if (!scale) {
      scales[trace.seriesKey] = { min: low, max: high };
    } else {
      scale.min = Math.min(scale.min, low);
      scale.max = Math.max(scale.max, high);
    }
  });
  Object.keys(scales).forEach(function (seriesKey) {
    var scale = scales[seriesKey];
    if (scale.min === scale.max) { scale.min -= 1; scale.max += 1; }
  });

  traces.forEach(function (trace) {
    var values = trace.values;
    if (!values.length) return;
    var scale = scales[trace.seriesKey];
    var min = scale.min;
    var max = scale.max;
    var span = max - min;
    trace.min = min;
    trace.max = max;
    trace.latest = values[values.length - 1];

    ctx.strokeStyle = trace.color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    values.forEach(function (value, index) {
      var x = (index / (HISTORY_POINTS - 1)) * width;
      var y = height - ((value - min) / span) * height;
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
}

function renderChartToggles(nodes) {
  var container = document.getElementById("chart-toggles");
  Object.keys(nodes).sort().forEach(function (nodeId) {
    SERIES.forEach(function (series) {
      var key = traceKey(nodeId, series.key);
      var id = "toggle-" + nodeId + "-" + series.key;
      if (document.getElementById(id)) return;
      if (chartVisible[key] === undefined) {
        chartVisible[key] = series.key === "actual_velocity_rpm";
      }
      var label = el("label", "chart-toggle");
      var box = document.createElement("input");
      box.type = "checkbox";
      box.id = id;
      box.checked = chartVisible[key];
      box.addEventListener("change", function (event) {
        chartVisible[key] = event.target.checked;
        renderChart(state.nodes);
      });
      label.appendChild(box);
      label.appendChild(el("span", null, " node " + nodeId + " / " + series.label));
      container.appendChild(label);
    });
  });
}

function renderChartLegend(traces) {
  var legend = document.getElementById("chart-legend");
  legend.innerHTML = "";
  if (!traces.length) {
    legend.appendChild(el("div", "note", "表示する波形が選ばれていません。"));
    return;
  }
  traces.forEach(function (trace) {
    var row = el("div", "chart-legend-row");
    var swatch = el("span", "chart-swatch");
    swatch.style.background = trace.color;
    row.appendChild(swatch);
    var range = trace.min === undefined
      ? "(データなし)"
      : "現在 " + fixed(trace.latest, 1) +
        " / 範囲 " + fixed(trace.min, 1) + " 〜 " + fixed(trace.max, 1);
    row.appendChild(el("span", null, trace.label + "  " + range));
    legend.appendChild(row);
  });
}

function renderChart(nodes) {
  renderChartToggles(nodes);
  var traces = visibleTraces(nodes);
  drawChart(document.getElementById("chart"), traces);
  renderChartLegend(traces);
}

function el(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function fixed(value, digits) {
  if (value === null || value === undefined) return "-";
  return Number(value).toFixed(digits);
}

function renderStatus(nodes) {
  var container = document.getElementById("nodes");
  container.innerHTML = "";
  Object.keys(nodes).sort().forEach(function (nodeId) {
    var snap = nodes[nodeId];
    var card = el("div", "node");
    card.appendChild(el("h3", null, "node " + nodeId + "  /  " + snap.state));

    var kv = el("dl", "kv");
    [
      ["モード (6061h)", snap.mode],
      ["Statusword (6041h)", "0x" + (snap.statusword >>> 0).toString(16).toUpperCase()],
      ["目標速度 (60FFh)", fixed(snap.target_velocity_rpm, 1) + " r/min"],
      ["指令速度 (606Bh)", fixed(snap.command_velocity_rpm, 1) + " r/min"],
      ["実速度 (606Ch)", fixed(snap.actual_velocity_rpm, 1) + " r/min"],
      ["位置 (6064h)", snap.actual_position + " inc"],
      ["トルク (6077h)", fixed(snap.torque_permille, 0) + " ‰"]
    ].forEach(function (pair) {
      kv.appendChild(el("dt", null, pair[0]));
      kv.appendChild(el("dd", null, String(pair[1])));
    });
    card.appendChild(kv);

    var bits = el("div", "bits");
    statuswordBits(snap.mode).forEach(function (entry) {
      var on = ((snap.statusword >> entry[0]) & 1) === 1;
      var chip = el("span", "bit" + (entry[0] === 3 ? " fault" : "") + (on ? " on" : ""),
        entry[0] + " " + entry[1]);
      bits.appendChild(chip);
    });
    card.appendChild(bits);

    var alarmText = snap.alarm === null || snap.alarm === undefined
      ? "アラーム: なし"
      : "アラーム: 0x" + Number(snap.alarm).toString(16).toUpperCase();
    var alarm = el("div", "alarm" + (snap.alarm ? " active" : ""), alarmText);
    if (snap.alarm_history && snap.alarm_history.length) {
      alarm.textContent += "  (履歴: " + snap.alarm_history.map(function (code) {
        return "0x" + Number(code).toString(16).toUpperCase();
      }).join(", ") + ")";
    }
    card.appendChild(alarm);

    container.appendChild(card);
  });
}

function renderCanLog(frames) {
  var pre = document.getElementById("canlog");
  var filter = state.filter.toLowerCase();
  var lines = frames.filter(function (frame) {
    if (!filter) return true;
    var haystack = (frame.text + " " + frame.can_id.toString(16) + " " + frame.data).toLowerCase();
    return haystack.indexOf(filter) !== -1;
  }).map(function (frame) {
    return fixed(frame.t, 3) + "  " +
      ("00" + frame.can_id.toString(16).toUpperCase()).slice(-3) + "  " +
      frame.text;
  });
  pre.textContent = lines.join("\n");
  pre.scrollTop = pre.scrollHeight;
}

document.getElementById("filter").addEventListener("input", function (event) {
  state.filter = event.target.value;
  renderCanLog(state.frames || []);
});

document.getElementById("pause").addEventListener("click", function (event) {
  state.canlogPaused = !state.canlogPaused;
  event.target.textContent = state.canlogPaused ? "再開" : "停止";
  if (!state.canlogPaused) renderCanLog(state.frames || []);
});

function onMessage(payload) {
  document.getElementById("simtime").textContent =
    "t = " + fixed(payload.sim_time, 3) + " s";
  state.nodes = payload.nodes;
  renderStatus(payload.nodes);
  pushHistory(payload.nodes);
  renderChart(payload.nodes);

  updateReplayFromPayload(payload);
  renderAlarms(payload.nodes);
  renderIo(payload.nodes);
  renderHwtoStatus(payload.nodes);
  if (window.omsimMotor3d) window.omsimMotor3d.update(payload);

  state.frames = payload.frames;
  if (!state.canlogPaused) renderCanLog(payload.frames);
}

function connect() {
  var badge = document.getElementById("conn");
  var socket = new WebSocket("ws://" + location.host + "/ws");
  socket.onopen = function () {
    badge.textContent = "接続中";
    badge.className = "badge ok";
  };
  socket.onclose = function () {
    badge.textContent = "切断";
    badge.className = "badge ng";
    setTimeout(connect, 1000);
  };
  socket.onmessage = function (event) {
    onMessage(JSON.parse(event.data));
  };
}

connect();

// --- CN4 配線 / HWTO パネル (P3.5) ---

var wiring = { relay: true };

function renderWiring(info) {
  wiring = info;
  document.getElementById("wiring-preset").value = info.preset || "";
  document.getElementById("wiring-hwto1").value = info.hwto1.source;
  document.getElementById("wiring-hwto2").value = info.hwto2.source;
  document.getElementById("relay-toggle").textContent =
    info.relay ? "安全リレーを切る" : "安全リレーを入れる";
}

function postWiring(body) {
  fetch("/api/wiring", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then(function (response) {
    if (!response.ok) return response.json().then(function (err) {
      throw new Error(err.detail || "配線の変更に失敗しました");
    });
    return response.json();
  }).then(renderWiring).catch(function (err) {
    document.getElementById("hwto-status").textContent = String(err.message || err);
  });
}

document.getElementById("wiring-preset").addEventListener("change", function (event) {
  postWiring({ preset: event.target.value });
});
["wiring-hwto1", "wiring-hwto2"].forEach(function (id) {
  document.getElementById(id).addEventListener("change", function () {
    postWiring({
      hwto1: document.getElementById("wiring-hwto1").value,
      hwto2: document.getElementById("wiring-hwto2").value
    });
  });
});
document.getElementById("relay-toggle").addEventListener("click", function () {
  postWiring({ relay: !wiring.relay });
});

function renderHwtoStatus(nodes) {
  var container = document.getElementById("hwto-status");
  container.innerHTML = "";
  Object.keys(nodes).sort().forEach(function (nodeId) {
    var snap = nodes[nodeId];
    var hwto = snap.hwto || {};
    var row = el("div", "hwto-row");
    row.appendChild(el("span", "hwto-node", "node " + nodeId));
    [
      ["HWTO1 入力", hwto.hwto1_on, true],
      ["HWTO2 入力", hwto.hwto2_on, true],
      ["動力遮断", snap.power_cut, false],
      ["ETO", hwto.eto_active, false],
      ["EDM-MON", hwto.edm_mon, false],
      ["HWTOIN-MON", hwto.hwtoin_mon, false],
      ["ブレーキ保持", snap.brake_engaged, false]
    ].forEach(function (item) {
      var on = Boolean(item[1]);
      // 入力は「ON が正常」、それ以外は「ON が異常寄り」なので色を分ける
      var good = item[2] ? on : !on;
      var chip = el("span", "lamp " + (good ? "lamp-on" : "lamp-warn"),
        item[0] + ": " + (on ? "ON" : "OFF"));
      row.appendChild(chip);
    });
    container.appendChild(row);
  });
}

// 配線の取得は「通常運転だと分かってから」1 回だけ行う。再生モードには配線が
// 無いので、先に投げると 409 がブラウザのコンソールに残ってしまう。
// 応答が失敗したときは HWTO パネルごと隠す (落ちない)。
var wiringRequested = false;

function loadWiringOnce() {
  if (wiringRequested) return;
  wiringRequested = true;
  fetch("/api/wiring").then(function (response) {
    if (!response.ok) {
      document.getElementById("pane-hwto").hidden = true;
      return null;
    }
    return response.json();
  }).then(function (info) { if (info) renderWiring(info); });
}

// --- アラームモニタ / I/O モニタ (P6) ---

// HP-5143E 60FDh/60FEh 実測の既定機能名。bit16-31 が R-IN / R-OUT。
var R_IN_NAMES = [
  "S-ON", "PLOOP-MODE", "TRQ-LMT", "CLR", "QSTOP", "STOP", "FREE", "ALM-RST",
  "D-SEL0", "D-SEL1", "D-SEL2", "D-SEL3", "D-SEL4", "D-SEL5", "D-SEL6", "D-SEL7"
];
var R_OUT_NAMES = [
  "SON-MON", "PLOOP-MON", "TRQ-LMTD", "RDY-DD-OPE", "ABSPEN", "STOP_R",
  "FREE_R", "ALM-A", "SYS-BSY", "IN-POS", "RDY-HOME-OPE", "RDY-FWRV-OPE",
  "RDY-SD-OPE", "MOVE", "VA", "TLC"
];
var R_IO_BASE_BIT = 16;

function renderAlarms(nodes) {
  var container = document.getElementById("alarms");
  container.innerHTML = "";
  Object.keys(nodes).sort().forEach(function (nodeId) {
    var snap = nodes[nodeId];
    var card = el("div", "node");
    var active = snap.alarm === null || snap.alarm === undefined
      ? "なし"
      : "0x" + Number(snap.alarm).toString(16).toUpperCase() +
        (snap.alarm_name ? " " + snap.alarm_name : "");
    card.appendChild(el("h3", null, "node " + nodeId + " / 現在アラーム: " + active));

    var history = snap.alarm_history_decoded || [];
    if (!history.length) {
      card.appendChild(el("div", "note", "履歴 (1003h): なし"));
    } else {
      var list = el("div", "bits");
      history.forEach(function (entry, position) {
        list.appendChild(el("span", "bit",
          (position + 1) + ": 0x" + entry.code.toString(16).toUpperCase() +
          " " + (entry.name || "") +
          " (EMCY 0x" + entry.emcy.toString(16).toUpperCase() + ")"));
      });
      card.appendChild(list);
    }
    container.appendChild(card);
  });
}

function renderIoRow(label, names, value) {
  var row = el("div", "hwto-row");
  row.appendChild(el("span", "hwto-node", label));
  names.forEach(function (name, bit) {
    var on = ((value >>> (R_IO_BASE_BIT + bit)) & 1) === 1;
    row.appendChild(el("span", "lamp" + (on ? " lamp-on" : ""), name));
  });
  return row;
}

function renderIo(nodes) {
  var container = document.getElementById("io");
  container.innerHTML = "";
  Object.keys(nodes).sort().forEach(function (nodeId) {
    var snap = nodes[nodeId];
    var card = el("div", "node");
    card.appendChild(el("h3", null, "node " + nodeId));
    card.appendChild(renderIoRow("R-IN", R_IN_NAMES, Number(snap.remote_inputs) || 0));
    card.appendChild(renderIoRow("R-OUT", R_OUT_NAMES, Number(snap.remote_outputs) || 0));
    container.appendChild(card);
  });
}

// --- 再生 (P7) ---
//
// omsim --replay で起動したときだけ /api/replay が生える。ペイロードに
// replay が入っていたら再生ペインを出す。

var replayState = { duration: 0, playing: false, seeking: false };

function postReplay(body) {
  return fetch("/api/replay", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then(function (response) { return response.json(); })
    .then(renderReplay);
}

function renderReplay(state) {
  replayState.duration = Number(state.duration) || 0;
  replayState.playing = Boolean(state.playing);
  document.getElementById("pane-replay").hidden = false;
  document.getElementById("replay-play").textContent =
    replayState.playing ? "停止" : "再生";
  document.getElementById("replay-position").textContent =
    fixed(state.position, 3) + " / " + fixed(replayState.duration, 3) + " s";
  if (!replayState.seeking && replayState.duration > 0) {
    document.getElementById("replay-seek").value =
      String(Math.round((state.position / replayState.duration) * 1000));
  }
}

document.getElementById("replay-play").addEventListener("click", function () {
  postReplay({ playing: !replayState.playing });
});

var seek = document.getElementById("replay-seek");
seek.addEventListener("input", function () { replayState.seeking = true; });
seek.addEventListener("change", function (event) {
  replayState.seeking = false;
  postReplay({ position: (Number(event.target.value) / 1000) * replayState.duration });
});

function updateReplayFromPayload(payload) {
  if (!payload.replay) {
    // 通常運転。ここで初めて配線を取りに行く。
    document.getElementById("pane-replay").hidden = true;
    loadWiringOnce();
    return;
  }
  document.getElementById("pane-hwto").hidden = true;
  renderReplay({
    position: payload.replay.position,
    duration: payload.replay.duration,
    playing: replayState.playing
  });
}
