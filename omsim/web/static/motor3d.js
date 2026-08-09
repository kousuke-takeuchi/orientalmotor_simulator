// node ごとのモーターを 3D 表示し、6064h (実位置) に合わせて軸を回す。
//
// 形状は docs/oriental_motor/ の STEP を実際にメッシュ化したもの
// (scripts/step_to_mesh.py で生成し、omsim/web/static/models/*.stl に置く)。
// 近似形状ではなく本物の外形を表示する。
//
// app.js (クラシックスクリプト) から呼べるよう window.omsimMotor3d に生やす。
import * as THREE from "./vendor/three.module.min.js";
import { STLLoader } from "./vendor/STLLoader.js";

// 表示するモデル。STEP の実寸 (mm) をそのまま使う。
var MODELS = [
  { url: "/static/models/A1861_F.stl", color: 0x9aa4b2 },
  { url: "/static/models/A1806.stl", color: 0x5d6672 }
];

var NODE_SPACING = 320.0;

var COLOR_CUT = 0xb26a6a;   // 動力遮断中 (トルクが出せない)

var scene = null;
var camera = null;
var renderer = null;
var motors = {};   // nodeId -> { group, shaft, body }
var view = { yaw: 0.6, pitch: 0.35, distance: 700, targetX: 0 };

function makeMotor() {
  // 実物のメッシュを読み込む。読み込み中は空の Group を返し、届いた順に足す。
  var group = new THREE.Group();
  var parts = [];
  var loader = new STLLoader();
  MODELS.forEach(function (entry) {
    loader.load(entry.url, function (geometry) {
      geometry.computeVertexNormals();
      var material = new THREE.MeshLambertMaterial({ color: entry.color });
      var mesh = new THREE.Mesh(geometry, material);
      mesh.userData.baseColor = entry.color;
      group.add(mesh);
      parts.push(mesh);
      render();
    }, undefined, function (err) {
      // 読めなかったことを黙って隠さない (近似形状で代替もしない)。
      console.error("3D モデルを読み込めません: " + entry.url, err);
    });
  });
  // STEP は housing と軸が 1 つのソリッドなので、軸だけを取り出して回すことが
  // できない。そこで出力軸の実際の軸線 (原点まわり・Z 軸。半径 47mm の円筒面から
  // 実測) の延長上、モデルの外側に回転指標を置いて回転量が見えるようにする。
  var marker = new THREE.Mesh(
    new THREE.BoxGeometry(8, 70, 8),
    new THREE.MeshLambertMaterial({ color: 0xffcf7e })
  );
  var shaft = new THREE.Group();
  marker.position.y = 35;
  shaft.add(marker);
  var hub = new THREE.Mesh(
    new THREE.CylinderGeometry(6, 6, 60, 16),
    new THREE.MeshLambertMaterial({ color: 0xffcf7e })
  );
  hub.rotation.x = Math.PI / 2;
  shaft.add(hub);
  shaft.position.set(0, 0, -130);
  group.add(shaft);
  return { group: group, shaft: shaft, parts: parts };
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
  camera.lookAt(view.targetX, 60, 0);
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
    motor.parts.forEach(function (mesh) {
      mesh.material.color.setHex(cut ? COLOR_CUT : mesh.userData.baseColor);
    });
  });
  render();
}

window.omsimMotor3d = { init: initMotor3d, update: updateMotor3d, angleRad: angleRad };

// type="module" のスクリプトは defer 相当なので、DOM は既にある。
var container = document.getElementById("motor3d");
if (container) initMotor3d(container);
