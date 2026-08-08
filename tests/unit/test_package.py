import sys

import omsim


def test_version_is_exposed():
    assert isinstance(omsim.__version__, str)
    assert omsim.__version__ != ""


def test_runs_on_python_38_or_newer():
    assert sys.version_info >= (3, 8)
