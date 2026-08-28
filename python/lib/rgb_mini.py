from machine import Pin, Signal


class RGBLed:
    OFF = 0
    RED = 0b100
    GREEN = 0b010
    BLUE = 0b001
    YELLOW = 0b110
    MAGENTA = 0b101
    CYAN = 0b011
    WHITE = 0b111

    def __init__(self, pin_r, pin_g, pin_b, inverted=True):
        self._r = Signal(Pin(pin_r, mode=Pin.OUT, value=False), invert=inverted)
        self._g = Signal(Pin(pin_g, mode=Pin.OUT, value=False), invert=inverted)
        self._b = Signal(Pin(pin_b, mode=Pin.OUT, value=False), invert=inverted)
        self.color = self.OFF
        self.set(self.OFF)

    def set(self, code):
        self.color = code
        self._r(1 if code & 0b100 else 0)
        self._g(1 if code & 0b010 else 0)
        self._b(1 if code & 0b001 else 0)
