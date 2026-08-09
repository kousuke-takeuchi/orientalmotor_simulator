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

var state = { paused: false, filter: "", nodes: {} };

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

function onMessage(payload) {
  document.getElementById("simtime").textContent =
    "t = " + fixed(payload.sim_time, 3) + " s";
  state.nodes = payload.nodes;
  renderStatus(payload.nodes);
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
    if (state.paused) return;
    onMessage(JSON.parse(event.data));
  };
}

connect();
