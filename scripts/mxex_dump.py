"""MEXE02 の .mxex からパラメータ値を読み出す。

.mxex は BOM 付きの XML (`FileDataTree`)。パラメータの正本は `<NetIds>` の
`<netid id="..." val="..."><att key="bank" val="..."/></netid>` で、
`MetaDatas` の `communicationdatas` はその写し (Bank/Address 形式)。

netid とパラメータ名の対応は HP-5141J「7 アドレスコード一覧」の NET-ID 列。
確認済みの対応は docs/oriental_motor/address-codes.md にある。

使い方:
    python3 scripts/mxex_dump.py <file.mxex> [netid ...]
"""
import io
import re
import sys

_NETID_RE = re.compile(r'<netid id="(\d+)" val="(-?\d+)"')


def parse_mxex_netids(text):
    """{netid: value} を返す。"""
    return dict(
        (int(m.group(1)), int(m.group(2))) for m in _NETID_RE.finditer(text))


def mxex_netids(path):
    with io.open(path, encoding="utf-8-sig") as handle:
        return parse_mxex_netids(handle.read())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: mxex_dump.py <file.mxex> [netid ...]")
        return 1
    values = mxex_netids(argv[0])
    wanted = [int(a, 0) for a in argv[1:]]
    if not wanted:
        print("{}: netid {} 件".format(argv[0], len(values)))
        return 0
    for netid in wanted:
        print("netid {} = {}".format(
            netid, values[netid] if netid in values else "なし"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
