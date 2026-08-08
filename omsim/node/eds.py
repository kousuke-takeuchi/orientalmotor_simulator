"""EDS ファイルの読み込み。仕様の正本は docs/oriental_motor/*.eds。"""
import os

import canopen

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EDS_DIR = os.path.join(_REPO_ROOT, "docs", "oriental_motor")
DEFAULT_EDS_PATH = os.path.join(EDS_DIR, "BLVD-KRD_CANopen_V400.eds")


def find_eds(name_or_path):
    """パスならそのまま、ファイル名だけなら docs/oriental_motor/ から探す。"""
    if os.path.isfile(name_or_path):
        return os.path.abspath(name_or_path)
    candidate = os.path.join(EDS_DIR, name_or_path)
    if os.path.isfile(candidate):
        return candidate
    raise FileNotFoundError("EDS が見つかりません: {}".format(name_or_path))


def load_eds(path):
    return canopen.import_od(find_eds(path))
