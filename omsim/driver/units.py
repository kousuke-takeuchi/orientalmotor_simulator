"""単位変換。HP-5141J 第1章1節「単位設定」(p12)、6091h / 608Fh。

内部表現は increment/s に統一する。
"""
from omsim.driver.errors import ABORT_VALUE_RANGE, ObjectAccessError


class UnitConverter(object):
    def __init__(
        self,
        encoder_increments=3600,
        motor_revolutions=1,
        gear_motor_revolutions=1,
        gear_shaft_revolutions=1,
    ):
        self.encoder_increments = encoder_increments
        self.motor_revolutions = motor_revolutions
        self.gear_motor_revolutions = gear_motor_revolutions
        self.gear_shaft_revolutions = gear_shaft_revolutions

    @property
    def gear_ratio(self):
        return float(self.gear_motor_revolutions) / float(self.gear_shaft_revolutions)

    @property
    def increments_per_shaft_rev(self):
        per_motor_rev = float(self.encoder_increments) / float(self.motor_revolutions)
        return per_motor_rev * self.gear_ratio

    def rpm_to_internal(self, rpm):
        return float(rpm) / 60.0 * self.increments_per_shaft_rev

    def internal_to_rpm(self, value):
        return float(value) * 60.0 / self.increments_per_shaft_rev

    def set_gear_ratio(self, motor_revolutions, shaft_revolutions):
        if motor_revolutions <= 0 or shaft_revolutions <= 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "6091h に 0 以下は設定できません")
        self.gear_motor_revolutions = motor_revolutions
        self.gear_shaft_revolutions = shaft_revolutions

    def set_encoder_resolution(self, increments, motor_revolutions):
        if increments <= 0 or motor_revolutions <= 0:
            raise ObjectAccessError(ABORT_VALUE_RANGE, "608Fh に 0 以下は設定できません")
        self.encoder_increments = increments
        self.motor_revolutions = motor_revolutions
