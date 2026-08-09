"""STEP を Web 表示用のメッシュ (バイナリ STL) に変換する。

Web で本物の 3D モデルを出すためのビルド時ツール。実行時の依存には
しない (生成した STL をリポジトリに置き、Web はそれだけを読む)。

変換には gmsh の OpenCASCADE を使う。gmsh は **このスクリプトを回すときだけ**
必要で、requirements.txt には入れない:

    pip3 install --user gmsh
    python3 scripts/step_to_mesh.py docs/oriental_motor/A1861_F.step \\
        omsim/web/static/models/A1861_F.stl

メッシュの粗さは --size で指定する [mm]。既定は 3mm で、A1861_F がおよそ
1MB 程度に収まる。細かくすると Web に載せる STL が大きくなる。
"""
import argparse
import os
import sys


def convert(step_path, stl_path, size=3.0, verbose=False):
    import gmsh

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 1 if verbose else 0)
        gmsh.model.add(os.path.basename(step_path))
        gmsh.model.occ.importShapes(step_path)
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", size)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", size / 4.0)
        # 表面だけあれば表示できる (2 次元メッシュ)。
        gmsh.model.mesh.generate(2)
        gmsh.option.setNumber("Mesh.Binary", 1)
        gmsh.write(stl_path)
    finally:
        gmsh.finalize()
    return os.path.getsize(stl_path)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="step_to_mesh")
    parser.add_argument("step")
    parser.add_argument("stl")
    parser.add_argument("--size", type=float, default=3.0, help="メッシュの代表長さ [mm]")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    directory = os.path.dirname(os.path.abspath(args.stl))
    if not os.path.isdir(directory):
        os.makedirs(directory)
    written = convert(args.step, args.stl, size=args.size, verbose=args.verbose)
    print("{} -> {} ({:,} バイト, 代表長さ {} mm)".format(
        args.step, args.stl, written, args.size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
