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

## STLLoader.js

Three.js の `examples/jsm/loaders/STLLoader.js`（同じ 0.169.0）。`import ... from 'three'`
を同梱物への相対パス `'./three.module.min.js'` に書き換えている（バンドラを使わないため）。

## models/

`omsim/web/static/models/*.stl` は `docs/oriental_motor/*.step` を
`scripts/step_to_mesh.py` でメッシュ化したもの。生成には gmsh が要るが、
**実行時の依存ではない**（生成物だけをリポジトリに置く）。

```bash
pip3 install --user gmsh   # 変換のときだけ
python3 scripts/step_to_mesh.py docs/oriental_motor/A1861_F.step \
    omsim/web/static/models/A1861_F.stl --size 8
```
