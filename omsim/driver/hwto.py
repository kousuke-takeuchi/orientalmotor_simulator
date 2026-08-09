"""HWTO (動力遮断機能) のモデル。can / canopen を import しないこと。

参照 (すべて pdftotext による実測):
  HP-5139J p21     : CN4 ピンアサイン。11/12 = HWTO1+/HWTO1−、26/27 = HWTO2+/HWTO2−、
                     25 = +V、13 = 0V、14/28 = EDM−/EDM+
  HP-5141J p204-212: HWTO1 OFF = インバータ上アーム遮断 / HWTO2 OFF = 下アーム遮断。
                     両方 OFF を検出すると「動力遮断+ETO 状態」(無励磁・ETO-MON ON・
                     電磁ブレーキ保持)。両方 ON にしてから ETO-CLR で解除。
                     1ms 以下のオフショットパルスでは動作しない。
                     EDM-MON は両方 OFF のときだけ ON。HWTOIN-MON はどちらか OFF で ON。
  HP-5143E 4.5     : EMCY FF53h/81h = HWTO input circuit error、
                     FF68h/81h = HWTO input detection Non-excitation
  HP-5143E 60FDh   : bit3 HWTO = 「どちらかの HWTO 入力が active」

用語: 入力 ON = DC24V が来ている = 正常。入力 OFF = HWTO が働いている状態。
"""

# 自己診断用オフショットパルスの上限 [ms]。これ以下の OFF は無視する。
OFFSHOT_PULSE_MS = 1.0

ALARM_CIRCUIT = "circuit"     # 53h HWTO 入力回路異常
ALARM_DETECTED = "detected"   # 68h HWTO 入力検出


class HwtoModel(object):
    def __init__(self, alarm_on_off_input=False, dual_mismatch_delay_ms=0):
        # MEXE02 パラメータ「HWTO 入力 OFF 時アラーム発生」(初期値 無効)
        self.alarm_on_off_input = bool(alarm_on_off_input)
        # MEXE02 パラメータ「HWTO-2 重系異常検出遅延時間」
        # 0-10 は無効、11-100 が ms 指定 (初期値 0 = 無効)
        self.dual_mismatch_delay_ms = int(dual_mismatch_delay_ms)

        self.hwto1_on = True
        self.hwto2_on = True
        self._off_ms = [0.0, 0.0]     # 各チャンネルが OFF になってからの経過 [ms]
        self._cut = [False, False]    # オフショット除去後の「遮断中」フラグ
        self.eto_active = False
        self._pending_alarm = None
        self._circuit_alarm_raised = False
        self._detected_alarm_raised = False

    # --- 入力 ---

    def set_inputs(self, hwto1_on, hwto2_on, dt):
        """1 制御周期ぶん進める。dt は秒。"""
        self.hwto1_on = bool(hwto1_on)
        self.hwto2_on = bool(hwto2_on)
        dt_ms = dt * 1000.0
        for channel, is_on in enumerate((self.hwto1_on, self.hwto2_on)):
            if is_on:
                self._off_ms[channel] = 0.0
                self._cut[channel] = False
            else:
                self._off_ms[channel] += dt_ms
                if self._off_ms[channel] > OFFSHOT_PULSE_MS:
                    self._cut[channel] = True

        if self._cut[0] and self._cut[1]:
            self.eto_active = True

        self._update_alarms()

    def _update_alarms(self):
        if self.power_cut:
            if self.alarm_on_off_input and not self._detected_alarm_raised:
                self._pending_alarm = ALARM_DETECTED
                self._detected_alarm_raised = True
        else:
            self._detected_alarm_raised = False

        if not self._mismatch_detection_enabled():
            return
        if self._cut[0] == self._cut[1]:
            # 両方 OFF になった、または両方 ON に戻った。監視のやり直し。
            self._circuit_alarm_raised = self._circuit_alarm_raised and self.eto_active
            if not self._cut[0]:
                self._circuit_alarm_raised = False
            return
        # 片方だけ OFF。その OFF が続いている時間が閾値を超えたら 53h。
        elapsed = self._off_ms[0] if self._cut[0] else self._off_ms[1]
        if elapsed > self.dual_mismatch_delay_ms and not self._circuit_alarm_raised:
            self._pending_alarm = ALARM_CIRCUIT
            self._circuit_alarm_raised = True

    def _mismatch_detection_enabled(self):
        # 0-10 は「無効」。11-100 ms が有効範囲 (HP-5141J p212 実測)。
        return self.dual_mismatch_delay_ms > 10

    # --- 出力 ---

    @property
    def power_cut(self):
        """どちらかのアームが遮断されている = トルクを出せない。"""
        return self._cut[0] or self._cut[1]

    @property
    def hwtoin_mon(self):
        """HWTOIN-MON 出力: どちらか一方でも OFF なら ON。60FDh bit3 と同じ。"""
        return self.power_cut

    @property
    def edm_mon(self):
        """EDM-MON 出力: 両方 OFF のときだけ ON。"""
        return self._cut[0] and self._cut[1]

    @property
    def eto_mon(self):
        return self.eto_active

    @property
    def pending_alarm(self):
        return self._pending_alarm

    def take_pending_alarm(self):
        alarm, self._pending_alarm = self._pending_alarm, None
        return alarm

    # --- 解除 ---

    def clear_eto(self):
        """ETO-CLR。両方の入力が ON に戻っているときだけ成功する。"""
        if self.power_cut:
            return False
        self.eto_active = False
        return True
