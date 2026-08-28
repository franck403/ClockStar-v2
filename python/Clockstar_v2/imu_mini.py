import math
from micropython import const


class LSM6DS3TR:
    WHO_AM_I_VAL = const(0x6A)
    REG_WHO_AM_I = const(0x0F)
    REG_CTRL1_XL = const(0x10)
    REG_CTRL2_G = const(0x11)
    REG_OUT_X_L_XL = const(0x28)
    REG_OUT_Y_L_XL = const(0x2A)
    REG_OUT_Z_L_XL = const(0x2C)
    REG_OUT_X_L_GY = const(0x22)
    REG_OUT_Y_L_GY = const(0x24)
    REG_OUT_Z_L_GY = const(0x26)

    def __init__(self, i2c, addr=0x6A):
        self.i2c = i2c
        self.addr = addr

    def begin(self):
        try:
            if self._get(self.REG_WHO_AM_I) != self.WHO_AM_I_VAL:
                return False
        except OSError:
            return False
        self._set(self.REG_CTRL1_XL, 0x44)  # accel 104Hz, +/-16g
        self._set(self.REG_CTRL2_G, 0x4C)   # gyro 104Hz, 2000dps
        return True

    def _set(self, reg, val):
        self.i2c.writeto_mem(self.addr, reg, bytes([val]))

    def _get(self, reg):
        return self.i2c.readfrom_mem(self.addr, reg, 1)[0]

    def _get16(self, reg):
        v = self._get(reg) + self._get(reg + 1) * 256
        return v if v < 0x8000 else v - 0x10000

    def _accel(self, reg):
        return self._get16(reg) * 0.488 / 1000.0

    def _gyro(self, reg):
        return self._get16(reg) * 70.0 * math.pi / 180.0 / 1000.0

    def get_accel(self):
        return (self._accel(self.REG_OUT_X_L_XL),
                self._accel(self.REG_OUT_Y_L_XL),
                self._accel(self.REG_OUT_Z_L_XL))

    def get_gyro(self):
        return (self._gyro(self.REG_OUT_X_L_GY),
                self._gyro(self.REG_OUT_Y_L_GY),
                self._gyro(self.REG_OUT_Z_L_GY))
