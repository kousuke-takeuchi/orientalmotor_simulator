"""MEXE02 の .mxex をシミュレータへ適用する / 2 ファイルを比較する。

netid とオブジェクトの対応は **CANopen index = 0x4000 + netid** (bank 1)。
設計書 2.3 の対応で、P5 でアドレスコード表 (HP-5141J 7 章) からも裏を取った
(netid 361 = 4169h「(HOME) 2 センサ原点復帰の戻りステップ数」、
netid 400 = 4190h 相当の HWTO パラメータ、いずれも netid == Modbus 上位 // 2)。

適用できなかったものは黙って捨てず、必ず件数で報告する。
"""
import logging

from omsim.driver.errors import ObjectAccessError
from scripts.mxex_dump import mxex_netids

logger = logging.getLogger(__name__)

MANUFACTURER_INDEX_BASE = 0x4000


def mxex_to_objects(netids):
    """{netid: 値} を {CANopen index: 値} に変換する。"""
    return dict(
        (MANUFACTURER_INDEX_BASE + int(netid), value)
        for netid, value in netids.items())


def apply_mxex(model, path):
    """mxex の値を DriverModel に書き込み、結果の内訳を返す。

    OD に無い index (unknown) と、範囲外などで拒否された値 (rejected) は
    件数と一覧を返す。1 件失敗しても残りは適用する。
    """
    objects = mxex_to_objects(mxex_netids(path))
    report = {
        "total": len(objects),
        "applied": 0,
        "unknown": 0,
        "rejected": 0,
        "unknown_indexes": [],
        "rejected_indexes": [],
    }
    for index in sorted(objects):
        value = objects[index]
        if (index, 0) not in model.router.implemented_keys():
            report["unknown"] += 1
            report["unknown_indexes"].append(index)
            continue
        try:
            model.write_object(index, 0, value)
        except ObjectAccessError as err:
            report["rejected"] += 1
            report["rejected_indexes"].append(index)
            logger.warning("mxex: %04Xh に %s を書けませんでした: %s", index, value, err)
            continue
        report["applied"] += 1
    logger.info(
        "mxex %s: %d 件中 %d 件を適用 (未知 %d / 拒否 %d)",
        path, report["total"], report["applied"], report["unknown"], report["rejected"])
    return report


def diff_mxex(path_a, path_b):
    """2 つの mxex を netid 単位で比較する。"""
    a = mxex_netids(path_a)
    b = mxex_netids(path_b)
    return {
        "only_in_a": dict((k, a[k]) for k in sorted(set(a) - set(b))),
        "only_in_b": dict((k, b[k]) for k in sorted(set(b) - set(a))),
        "different": dict(
            (k, (a[k], b[k])) for k in sorted(set(a) & set(b)) if a[k] != b[k]),
    }


def format_diff(result):
    lines = []
    for netid, values in result["different"].items():
        lines.append("netid {}: {} -> {}".format(netid, values[0], values[1]))
    for label, key in (("a のみ", "only_in_a"), ("b のみ", "only_in_b")):
        for netid, value in result[key].items():
            lines.append("{} netid {} = {}".format(label, netid, value))
    if not lines:
        lines.append("差分はありません")
    return lines
