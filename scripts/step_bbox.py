"""STEP (ISO-10303-21) ファイルから実寸 (バウンディングボックス) を取り出す。

3D 表示の形状寸法を目分量で決めないためのツール。CAD ツールが無い環境でも
「実物が何 mm か」だけは STEP から機械的に読める。

注意: CARTESIAN_POINT を全部拾ってはいけない。STEP には無限平面や軸の構造線が
含まれ、その原点が ±499000 のような値で入っているため、寸法が桁違いになる
(A1806.step で実際に発生)。実体の角は VERTEX_POINT から参照される点なので、
そこから辿った点だけを使う。

使い方:
    python3 scripts/step_bbox.py docs/oriental_motor/A1806.step
"""
import io
import re
import sys

_POINT_RE = re.compile(
    r"#(\d+)\s*=\s*CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(\s*"
    r"([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)")
_VERTEX_RE = re.compile(r"VERTEX_POINT\s*\(\s*'[^']*'\s*,\s*#(\d+)")


def parse_step_bbox(text):
    """STEP のテキストから {'x': (min,max), 'y':..., 'z':..., 'size': (dx,dy,dz)} を返す。"""
    points = {}
    for match in _POINT_RE.finditer(text):
        points[match.group(1)] = (
            float(match.group(2)), float(match.group(3)), float(match.group(4)))
    vertices = [points[i] for i in _VERTEX_RE.findall(text) if i in points]
    if not vertices:
        raise ValueError("VERTEX_POINT から参照される点が 1 つもありません")
    xs = [p[0] for p in vertices]
    ys = [p[1] for p in vertices]
    zs = [p[2] for p in vertices]
    bbox = {"x": (min(xs), max(xs)), "y": (min(ys), max(ys)), "z": (min(zs), max(zs))}
    bbox["size"] = (
        bbox["x"][1] - bbox["x"][0],
        bbox["y"][1] - bbox["y"][0],
        bbox["z"][1] - bbox["z"][0],
    )
    bbox["vertex_count"] = len(vertices)
    return bbox


def step_bbox(path):
    with io.open(path, encoding="latin-1") as handle:
        return parse_step_bbox(handle.read())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: step_bbox.py <file.step> [...]")
        return 1
    for path in argv:
        bbox = step_bbox(path)
        size = bbox["size"]
        print("{}: {:.1f} x {:.1f} x {:.1f} mm (頂点 {} 点)".format(
            path, size[0], size[1], size[2], bbox["vertex_count"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
