// node ごとのモーターを 3D 表示し、6064h (実位置) に合わせて軸を回す。
//
// 形状は STEP そのものではなくパラメトリックな近似。STEP -> メッシュ変換には
// CAD ツールが必要で、この環境 (VM / Windows とも) に無いため。寸法だけは
// scripts/step_bbox.py で実測した値を使い、目分量にしない。
//
// app.js (クラシックスクリプト) から呼べるよう window.omsimMotor3d に生やす。
import * as THREE from "./vendor/three.module.min.js";

// scripts/step_bbox.py の実測値 [mm]。
//   A1806.step   : 65.0 x 29.1 x 80.2
//   A1861_F.step : 111.0 x 218.0 x 191.0
var MOTOR_BODY_DIAMETER = 65.0;
var MOTOR_BODY_LENGTH = 80.2;
// A1861_F は取付ブラケット相当。実寸の外形 (111 x 218 x 191) のうち、
// 板厚は STEP から機械的には取れないので 10mm と仮定している (ここだけ推定)。
var BRACKET_WIDTH = 111.0;
var BRACKET_HEIGHT = 191.0;
var BRACKET_THICKNESS = 10.0;
var SHAFT_DIAMETER = 12.0;
var SHAFT_LENGTH = 40.0;
var NODE_SPACING = 220.0;

var COLOR_BODY = 0x9aa4b2;
var COLOR_BODY_CUT = 0xb26a6a;   // 動力遮断中 (トルクが出せない)
var COLOR_BRACKET = 0x5d6672;
var COLOR_SHAFT = 0xd8dee9;
var COLOR_KEY = 0x2b3038;        // 回転が見えるようにする目印

var scene = null;
var camera = null;
var renderer = null;
var motors = {};   // nodeId -> { group, shaft, body }
var view = { yaw: 0.6, pitch: 0.35, distance: 520, targetX: 0 };

function makeMotor() {
  var group = new THREE.Group();

  var body = new THREE.Mesh(
    new THREE.CylinderGeometry(
      MOTOR_BODY_DIAMETER / 2, MOTOR_BODY_DIAMETER / 2, MOTOR_BODY_LENGTH, 32),
    new THREE.MeshLambertMaterial({ color: COLOR_BODY })
  );
  // 円筒の既定軸は Y。軸方向を Z に倒して「横向きのモーター」にする。
  body.rotation.x = Math.PI / 2;
  body.position.z = -MOTOR_BODY_LENGTH / 2;
  group.add(body);

  var bracket = new THREE.Mesh(
    new THREE.BoxGeometry(BRACKET_WIDTH, BRACKET_HEIGHT, BRACKET_THICKNESS),
    new THREE.MeshLambertMaterial({ color: COLOR_BRACKET })
  );
  bracket.position.z = -MOTOR_BODY_LENGTH - BRACKET_THICKNESS / 2;
  group.add(bracket);

  var shaft = new THREE.Group();
  var shaftMesh = new THREE.Mesh(
    new THREE.CylinderGeometry(
      SHAFT_DIAMETER / 2, SHAFT_DIAMETER / 2, SHAFT_LENGTH, 24),
    new THREE.MeshLambertMaterial({ color: COLOR_SHAFT })
  );
  shaftMesh.rotation.x = Math.PI / 2;
  shaftMesh.position.z = SHAFT_LENGTH / 2;
  shaft.add(shaftMesh);

  // 軸だけだと回っているか分からないので、キー溝に相当する平板を付ける。
  var key = new THREE.Mesh(
    new THREE.BoxGeometry(SHAFT_DIAMETER * 1.6, SHAFT_DIAMETER * 0.35, SHAFT_LENGTH * 0.9),
    new THREE.MeshLambertMaterial({ color: COLOR_KEY })
  );
  key.position.set(0, SHAFT_DIAMETER / 2, SHAFT_LENGTH / 2);
  shaft.add(key);

  group.add(shaft);
  return { group: group, shaft: shaft, body: body };
}

function layout() {
  var ids = Object.keys(motors).sort();
  ids.forEach(function (nodeId, index) {
    motors[nodeId].group.position.x = (index - (ids.length - 1) / 2) * NODE_SPACING;
  });
}

function ensureMotor(nodeId) {
  if (motors[nodeId]) return motors[nodeId];
  var motor = makeMotor();
  motors[nodeId] = motor;
  scene.add(motor.group);
  layout();
  return motor;
}

// 実位置 (inc) と 1 回転あたりの inc から軸の角度 [rad] を出す。
// increments_per_revolution はサーバのスナップショットから受け取る
// (JS 側に定数を二重に持たない)。
export function angleRad(position, incrementsPerRevolution) {
  var perRev = Number(incrementsPerRevolution);
  if (!perRev) return 0;
  return (Number(position) || 0) / perRev * Math.PI * 2;
}

function resize() {
  if (!renderer) return;
  var element = renderer.domElement;
  var width = element.clientWidth || 640;
  var height = element.clientHeight || 320;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function render() {
  camera.position.set(
    view.targetX + view.distance * Math.cos(view.pitch) * Math.sin(view.yaw),
    view.distance * Math.sin(view.pitch),
    view.distance * Math.cos(view.pitch) * Math.cos(view.yaw)
  );
  camera.lookAt(view.targetX, 0, -MOTOR_BODY_LENGTH / 2);
  renderer.render(scene, camera);
}

function bindMouse(canvas) {
  var dragging = false;
  var lastX = 0;
  var lastY = 0;
  canvas.addEventListener("mousedown", function (event) {
    dragging = true; lastX = event.clientX; lastY = event.clientY;
  });
  window.addEventListener("mouseup", function () { dragging = false; });
  window.addEventListener("mousemove", function (event) {
    if (!dragging) return;
    view.yaw += (event.clientX - lastX) * 0.01;
    view.pitch += (event.clientY - lastY) * 0.01;
    view.pitch = Math.max(-1.4, Math.min(1.4, view.pitch));
    lastX = event.clientX; lastY = event.clientY;
    render();
  });
  canvas.addEventListener("wheel", function (event) {
    event.preventDefault();
    view.distance = Math.max(150, Math.min(2000, view.distance + event.deltaY));
    render();
  }, { passive: false });
}

export function initMotor3d(container) {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x11151c);

  camera = new THREE.PerspectiveCamera(45, 2, 1, 8000);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  container.appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  var key = new THREE.DirectionalLight(0xffffff, 0.8);
  key.position.set(1, 1.5, 1);
  scene.add(key);

  bindMouse(renderer.domElement);
  window.addEventListener("resize", function () { resize(); render(); });
  resize();
  render();
}

export function updateMotor3d(payload) {
  if (!scene || !payload || !payload.nodes) return;
  Object.keys(payload.nodes).forEach(function (nodeId) {
    var snap = payload.nodes[nodeId];
    var motor = ensureMotor(nodeId);
    motor.shaft.rotation.z = angleRad(
      snap.actual_position, snap.increments_per_revolution);
    var cut = Boolean(snap.power_cut);
    motor.body.material.color.setHex(cut ? COLOR_BODY_CUT : COLOR_BODY);
  });
  render();
}

window.omsimMotor3d = { init: initMotor3d, update: updateMotor3d, angleRad: angleRad };

// type="module" のスクリプトは defer 相当なので、DOM は既にある。
var container = document.getElementById("motor3d");
if (container) initMotor3d(container);
