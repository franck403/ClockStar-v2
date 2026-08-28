from micropython import const


def _bcd2dec(b):
    return (b >> 4) * 10 + (b & 0x0F)


def _dec2bcd(d):
    return ((d // 10) << 4) | (d % 10)


def _clamp(v, lo, hi):
    return max(lo, min(v, hi))


class Time:
    __slots__ = ("year", "month", "day", "hours", "minutes", "seconds")

    def __init__(self, year=2000, month=1, day=1, hours=0, minutes=0, seconds=0):
        self.year = year
        self.month = month
        self.day = day
        self.hours = hours
        self.minutes = minutes
        self.seconds = seconds


class BM8563:
    ADDR = const(0x51)

    def __init__(self, i2c, address=ADDR):
        self.i2c = i2c
        self.addr = address
        self.time = Time()

    def begin(self):
        try:
            self.i2c.writeto(self.addr, bytearray([0x00, 0x00, 0x00]))
            self.get_time()
        except OSError:
            return False
        return True

    def get_time(self):
        self.i2c.writeto(self.addr, bytearray([0x02]))
        data = self.i2c.readfrom(self.addr, 7)

        t = self.time
        t.seconds = _bcd2dec(data[0] & 0x7F)
        t.minutes = _bcd2dec(data[1] & 0x7F)
        t.hours = _bcd2dec(data[2] & 0x3F)
        t.day = _bcd2dec(data[3] & 0x3F)
        t.month = _bcd2dec(data[5] & 0x1F)
        century = 100 if (data[5] & 0x80) else 0
        t.year = _bcd2dec(data[6]) + century + 1900
        return t

    def set_time(self, t):
        t.seconds = _clamp(t.seconds, 0, 59)
        t.minutes = _clamp(t.minutes, 0, 59)
        t.hours = _clamp(t.hours, 0, 23)
        t.day = _clamp(t.day, 1, 31)
        t.month = _clamp(t.month, 1, 12)
        t.year = _clamp(t.year, 1900, 2099)

        month_byte = _dec2bcd(t.month) & 0x1F
        if t.year >= 2000:
            month_byte |= 0x80

        data = bytearray([
            0x02,
            _dec2bcd(t.seconds) & 0x7F,
            _dec2bcd(t.minutes) & 0x7F,
            _dec2bcd(t.hours) & 0x3F,
            _dec2bcd(t.day) & 0x3F,
            0x00,  # weekday, ignore
            month_byte,
            _dec2bcd(t.year % 100),
        ])
        self.i2c.writeto(self.addr, data)
        self.get_time()
