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
# メーカ固有オブジェクトは 4000h-4FFFh。netid がこれを超えるものは CANopen に
# 対応する index が無く、MEXE02 (PC Link / Modbus) からしか触れない。
MANUFACTURER_NETID_MAX = 0x0FFF

# MEXE02 専用パラメータのうち、シミュレータが実際に反映できるもの。
# R-IN0 機能選択 = NET-ID 17408 (4400h)、以降 R-IN1, R-IN2, ... と続く
# (HP-5141J 13-10 実測)。
R_IN_FUNCTION_NETID_BASE = 0x4400


def mxex_to_objects(netids):
    """{netid: 値} を {CANopen index: 値} に変換する。

    CANopen のメーカ固有領域に収まる netid だけを返す。
    """
    return dict(
        (MANUFACTURER_INDEX_BASE + int(netid), value)
        for netid, value in netids.items()
        if int(netid) <= MANUFACTURER_NETID_MAX)


def _apply_mexe02_only(model, netid, value):
    """CANopen に無いパラメータのうち、反映できるものを反映する。

    反映できたら True。できなければ False を返す (件数は呼び出し元が数える)。
    """
    from omsim.driver.io_functions import R_IN_SLOTS

    slot = int(netid) - R_IN_FUNCTION_NETID_BASE
    if 0 <= slot < R_IN_SLOTS:
        try:
            model.set_remote_input_function(slot, value)
        except ValueError as err:
            logger.warning("mxex: R-IN%d の機能割付 %s は不正です: %s", slot, value, err)
            return False
        return True
    return False


def apply_mxex(model, path):
    """mxex の値を DriverModel に書き込み、結果の内訳を返す。

    OD に無い index (unknown) と、範囲外などで拒否された値 (rejected) は
    件数と一覧を返す。1 件失敗しても残りは適用する。
    """
    netids = mxex_netids(path)
    objects = mxex_to_objects(netids)
    report = {
        "total": len(netids),
        "applied": 0,
        "unknown": 0,
        "rejected": 0,
        "mexe02_only": 0,
        "unknown_indexes": [],
        "rejected_indexes": [],
    }
    for netid in sorted(netids):
        if netid <= MANUFACTURER_NETID_MAX:
            continue
        if _apply_mexe02_only(model, netid, netids[netid]):
            report["applied"] += 1
        else:
            # CANopen に対応する index が無いパラメータ。「未知」とは分けて数える。
            report["mexe02_only"] += 1
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
        "mxex %s: %d 件中 %d 件を適用 (未知 %d / 拒否 %d / MEXE02 専用 %d)",
        path, report["total"], report["applied"], report["unknown"],
        report["rejected"], report["mexe02_only"])
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
