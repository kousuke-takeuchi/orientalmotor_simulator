"""CN4 の配線構成。「何が HWTO 入力を駆動するか」をデータとして持つ。

標準的な 2 重系配線も、実機の片系配線も、同じ HwtoModel のまま再現できる
ようにするための層。ドライバの挙動そのものは omsim/driver/hwto.py が持つ。

CN4 ピン (HP-5139J p21 実測):
  11/12 = HWTO1+/HWTO1−、26/27 = HWTO2+/HWTO2−、25 = +V、13 = 0V

入力ソース:
  relay  : 安全リレー connected。リレーが励磁されている間だけ ON
  jumper : 付属ジャンパー線で +V/0V へ短絡。常に ON (= 動力遮断を使わない)
  open   : 未接続。常に OFF
"""

SOURCES = ("relay", "jumper", "open")

HWTO_PINS = {"hwto1": "CN4 11/12", "hwto2": "CN4 26/27"}

PRESETS = {
    # 標準の 2 重系配線。安全リレーが両チャンネルを同時に切る。
    "standard": ("relay", "relay"),
    # 実機 (図面 08015VA-24M-AA-00)。安全リレーは HWTO1 だけを駆動し、
    # HWTO2 は 25(+V)-26 / 27-13(0V) の標準ジャンパで常時 ON。
    "pitakuru": ("relay", "jumper"),
    # 動力遮断機能を使わない配線。両方とも付属ジャンパーで短絡。
    "none": ("jumper", "jumper"),
}


class WiringError(ValueError):
    pass


class Cn4Wiring(object):
    def __init__(self, hwto1="relay", hwto2="relay"):
        for name, source in (("hwto1", hwto1), ("hwto2", hwto2)):
            if source not in SOURCES:
                raise WiringError(
                    "{} のソース {!r} は不正です。{} のどれかを指定してください".format(
                        name, source, "/".join(SOURCES)))
        self.hwto1 = hwto1
        self.hwto2 = hwto2

    @classmethod
    def preset(cls, name):
        if name not in PRESETS:
            raise WiringError(
                "配線プリセット {!r} は不明です。{} のどれかを指定してください".format(
                    name, "/".join(sorted(PRESETS))))
        return cls(*PRESETS[name])

    def _input_state(self, source, relay_energized):
        if source == "jumper":
            return True
        if source == "open":
            return False
        return bool(relay_energized)

    def hwto_inputs(self, relay_energized):
        """(hwto1_on, hwto2_on) を返す。ON = DC24V が来ている = 正常。"""
        return (
            self._input_state(self.hwto1, relay_energized),
            self._input_state(self.hwto2, relay_energized),
        )

    def describe(self):
        return {
            "hwto1": {"source": self.hwto1, "pins": HWTO_PINS["hwto1"]},
            "hwto2": {"source": self.hwto2, "pins": HWTO_PINS["hwto2"]},
        }

    def preset_name(self):
        """既知のプリセットに一致すればその名前、しなければ None。"""
        for name, sources in PRESETS.items():
            if sources == (self.hwto1, self.hwto2):
                return name
        return None
