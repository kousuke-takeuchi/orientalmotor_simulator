"""EDS に載るオブジェクトと、実装済みオブジェクトを突き合わせる。

「何を実装したか」ではなく「何がまだ実装されていないか」を機械的に出せる
ようにするためのモジュール。設計書 9 節の「未実装オブジェクトの一覧を
コマンドで出せるようにし、網羅の進捗を可視化する」に対応する。

canopen に依存しないよう、OD は「index -> オブジェクト」のマッピングと
して扱い、サブインデックスの有無はダックタイピングで判定する。
"""


def _iter_od_keys(od):
    """OD に含まれる (index, sub) を列挙する。"""
    for index in sorted(od):
        obj = od[index]
        subs = getattr(obj, "subindices", None)
        if subs:
            for sub in sorted(subs):
                yield (index, sub)
        else:
            yield (index, 0)


def coverage_report(od, router):
    implemented = router.implemented_keys()
    passthrough = router.passthrough_keys()

    total = 0
    implemented_count = 0
    passthrough_count = 0
    unimplemented = []
    for key in _iter_od_keys(od):
        total += 1
        if key in passthrough:
            passthrough_count += 1
        elif key in implemented:
            implemented_count += 1
        else:
            unimplemented.append(key)

    return {
        "total": total,
        "implemented": implemented_count,
        "passthrough": passthrough_count,
        "unimplemented": len(unimplemented),
        "unimplemented_list": sorted(unimplemented),
    }


def format_report(report):
    lines = [
        "EDS オブジェクト総数: {}".format(report["total"]),
        "  実装済み          : {}".format(report["implemented"]),
        "  値の保持のみ      : {}".format(report["passthrough"]),
        "  未実装            : {}".format(report["unimplemented"]),
        "",
        "未実装の一覧:",
    ]
    for index, sub in report["unimplemented_list"]:
        lines.append("  {:04X}h:{:02X}".format(index, sub))
    return "\n".join(lines)
