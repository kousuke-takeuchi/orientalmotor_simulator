"""HP-5141J「7 アドレスコード一覧」から NET-ID の表を抽出する。

`.mxex` は netid でパラメータを持つ。netid とパラメータ名の対応が無いと
mxex の中身を読めないため、PDF から機械的に起こす。

表の 1 行は次の形で pdftotext -layout に出る (名称は別行に折れることがある):
    <Modbus 上位> <Modbus 下位>  <名称>  ... <NET-ID>

実測で成り立つ関係: **NET-ID == Modbus 上位アドレス // 2**
(例: 800/801 -> 400、802/803 -> 401、816/817 -> 408)。
この不変条件を検査し、破る行は捨てずに報告する。

使い方:
    pdftotext -layout HP-5141J.pdf /tmp/5141J.txt
    python3 scripts/extract_address_codes.py /tmp/5141J.txt
"""
import collections
import io
import re
import sys

ROW_RE = re.compile(
    r"^\s*(\d{1,5})\s+(\d{1,5})\s+(.*?)\s{2,}(\d{1,5})\s*$")

AddressRow = collections.namedtuple(
    "AddressRow", ["modbus_upper", "modbus_lower", "name", "netid"])


def parse_address_codes(text):
    """(rows, skipped) を返す。skipped は不変条件を満たさなかった行数。"""
    rows = []
    skipped = 0
    for line in text.splitlines():
        match = ROW_RE.match(line)
        if not match:
            continue
        upper, lower, name, netid = match.groups()
        upper, lower, netid = int(upper), int(lower), int(netid)
        if lower != upper + 1:
            skipped += 1
            continue
        if netid != upper // 2:
            skipped += 1
            continue
        rows.append(AddressRow(upper, lower, name.strip(), netid))
    return rows, skipped


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: extract_address_codes.py <pdftotext-output.txt>")
        return 1
    with io.open(argv[0], encoding="utf-8") as handle:
        rows, skipped = parse_address_codes(handle.read())

    named = [row for row in rows if row.name]
    print("抽出した行: {} (うち名称つき {} / 名称が別行に折れて取れなかった {})".format(
        len(rows), len(named), len(rows) - len(named)))
    print("不変条件 (下位 == 上位+1 かつ NET-ID == 上位//2) を満たさず捨てた行: {}".format(
        skipped))
    for row in named:
        print("{}\t{}\t{}\t{}".format(row.netid, row.modbus_upper, row.modbus_lower, row.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
