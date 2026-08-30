from machine import Pin, Signal


class InputGPIO:
    def __init__(self, pins, inverted=False):
        self.n = len(pins)
        self._state = [False] * self.n
        self._on_press = [None] * self.n
        self._on_release = [None] * self.n
        self._signals = [
            Signal(Pin(p, mode=Pin.IN, pull=Pin.PULL_UP if inverted else Pin.PULL_DOWN),
                   invert=inverted)
            for p in pins
        ]

    def state(self, i):
        return self._state[i] if i < self.n else False

    def on_press(self, i, callback):
        if i < self.n:
            self._on_press[i] = callback

    def on_release(self, i, callback):
        if i < self.n:
            self._on_release[i] = callback

    def scan(self):
        for i, sig in enumerate(self._signals):
            pressed = bool(sig.value())
            if pressed != self._state[i]:
                self._state[i] = pressed
                cb = self._on_press[i] if pressed else self._on_release[i]
                if cb:
                    cb()

    def poll(self):
        self.scan()

    def was_pressed(self, i):
        return self.state(i)

    def is_pressed(self, i):
        return self.state(i)
