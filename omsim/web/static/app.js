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
  [11, "Internal limit active"],
  [12, "Speed is 0 (pv)"]
];

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

function drawChart(canvas, values, color) {
  var ctx = canvas.getContext("2d");
  var width = canvas.width = canvas.clientWidth;
  var height = canvas.height = canvas.clientHeight;
  ctx.clearRect(0, 0, width, height);

  if (!values.length) return;

  var min = Math.min.apply(null, values);
  var max = Math.max.apply(null, values);
  if (min === max) { min -= 1; max += 1; }
  var span = max - min;

  // 0 の基準線
  if (min < 0 && max > 0) {
    var zeroY = height - ((0 - min) / span) * height;
    ctx.strokeStyle = "#2b313b";
    ctx.beginPath();
    ctx.moveTo(0, zeroY);
    ctx.lineTo(width, zeroY);
    ctx.stroke();
  }

  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  values.forEach(function (value, index) {
    var x = (index / (HISTORY_POINTS - 1)) * width;
    var y = height - ((value - min) / span) * height;
    if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = "#6b7480";
  ctx.font = "10px sans-serif";
  ctx.fillText(max.toFixed(1), 4, 10);
  ctx.fillText(min.toFixed(1), 4, height - 3);
}

function renderCharts(nodes) {
  var container = document.getElementById("charts");
  Object.keys(nodes).sort().forEach(function (nodeId) {
    SERIES.forEach(function (series) {
      var id = "chart-" + nodeId + "-" + series.key;
      var wrapper = document.getElementById(id);
      if (!wrapper) {
        wrapper = el("div", "chart");
        wrapper.id = id;
        wrapper.appendChild(el("div", "chart-label",
          "node " + nodeId + " / " + series.label));
        wrapper.appendChild(document.createElement("canvas"));
        container.appendChild(wrapper);
      }
      drawChart(wrapper.querySelector("canvas"),
        chartHistory[nodeId] ? chartHistory[nodeId][series.key] : [], series.color);
    });
  });
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
    STATUSWORD_BITS.forEach(function (entry) {
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
  renderCharts(payload.nodes);

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
