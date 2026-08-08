"""driver 層が can / canopen に依存していないことを検証する。"""
import os
import re

DRIVER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "omsim",
    "driver",
)
FORBIDDEN = re.compile(r"^\s*(?:import|from)\s+(can|canopen)\b", re.MULTILINE)


def test_driver_layer_does_not_import_can_libraries():
    offenders = []
    for name in sorted(os.listdir(DRIVER_DIR)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(DRIVER_DIR, name)
        with open(path, encoding="utf-8") as handle:
            if FORBIDDEN.search(handle.read()):
                offenders.append(name)
    assert offenders == [], "driver 層が can/canopen を import している: {}".format(offenders)
