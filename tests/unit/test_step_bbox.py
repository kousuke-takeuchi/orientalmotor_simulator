import os

from scripts.step_bbox import parse_step_bbox, step_bbox

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STEP_DIR = os.path.join(HERE, "docs", "oriental_motor")

SYNTHETIC = """ISO-10303-21;
DATA;
#1 = CARTESIAN_POINT ( 'NONE', ( 0.0, 0.0, 0.0 ) ) ;
#2 = CARTESIAN_POINT ( 'NONE', ( 10.0, 20.0, 30.0 ) ) ;
#3 = CARTESIAN_POINT ( 'NONE', ( -499000.0, 499000.0, 0.0 ) ) ;
#4 = VERTEX_POINT ( 'NONE', #1 ) ;
#5 = VERTEX_POINT ( 'NONE', #2 ) ;
#6 = PLANE ( 'NONE', #3 ) ;
ENDSEC;
END-ISO-10303-21;
"""


def test_only_points_referenced_by_vertex_point_are_used():
    """構造線 (無限平面の原点など) の座標を bbox に混ぜない。

    STEP の CARTESIAN_POINT を全部拾うと ±499000 の構造線が入り、
    寸法が桁違いになる (実 STEP で確認済み)。
    """
    bbox = parse_step_bbox(SYNTHETIC)
    assert bbox["x"] == (0.0, 10.0)
    assert bbox["y"] == (0.0, 20.0)
    assert bbox["z"] == (0.0, 30.0)
    assert bbox["size"] == (10.0, 20.0, 30.0)


def test_a1806_actual_dimensions():
    bbox = step_bbox(os.path.join(STEP_DIR, "A1806.step"))
    x, y, z = bbox["size"]
    assert round(x, 1) == 65.0
    assert round(y, 1) == 29.1
    assert round(z, 1) == 80.2


def test_a1861f_actual_dimensions():
    bbox = step_bbox(os.path.join(STEP_DIR, "A1861_F.step"))
    x, y, z = bbox["size"]
    assert round(x, 1) == 111.0
    assert round(y, 1) == 218.0
    assert round(z, 1) == 191.0
