from machine import Pin, Signal

class RGBLed:
    def __init__(self, pin_r, pin_g, pin_b, inverted=True):
        self._r = Signal(Pin(pin_r, mode=Pin.OUT, value=False), invert=inverted)
        self._g = Signal(Pin(pin_g, mode=Pin.OUT, value=False), invert=inverted)
        self._b = Signal(Pin(pin_b, mode=Pin.OUT, value=False), invert=inverted)
        self.color = (0, 0, 0)
        self.set(0, 0, 0)

    def set(self, r, g, b):
        self.color = (r, g, b)
        self._r(r)
        self._g(g)
        self._b(b)