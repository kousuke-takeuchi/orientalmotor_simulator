# 同梱ライブラリ

omsim の Web モニタはオフライン前提（VM 上で動かし、CDN に到達できない環境がある）
のため、外部ホストを一切参照しない。使うライブラリはここに実物を置く。

| ファイル | 中身 | 版 | 出所 | ライセンス |
|---|---|---|---|---|
| `three.module.min.js` | Three.js 本体（ES module 版・minified） | **0.169.0** | `pitakuru_ws/ros_web_sim/node_modules/three/build/three.module.min.js` | MIT（`THREE-LICENSE.txt`） |

`examples/jsm`（OrbitControls など）は同梱していない。カメラ操作は `motor3d.js` の
自前実装で足りているため、依存を増やさない。

更新するときは版をこの表に書き直すこと。`tests/unit/test_web_static.py` が
この README に版が書かれていることを検査する。
