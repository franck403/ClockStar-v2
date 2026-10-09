"""Working piezo driver (installed by the Metronome extension).

Replaces the stock Clockstar_v2/piezo_mini.py, whose tone() is disabled.
Adds non-blocking start()/stop() on top of the blocking tone().
"""

import time
from machine import Pin, PWM


class Piezo:
    def __init__(self, pin):
        self._pin_num = pin
        self._pwm = None
        Pin(pin, Pin.OUT, value=0)

    def start(self, freq, duty_u16=32768):
        """Start a tone and return immediately; call stop() to end it."""
        self.stop()
        try:
            self._pwm = PWM(Pin(self._pin_num), freq=int(freq), duty_u16=duty_u16)
        except Exception as e:
            print("piezo start error:", e)
            self._pwm = None

    def stop(self):
        if self._pwm is not None:
            try:
                self._pwm.deinit()
            except Exception:
                pass
            self._pwm = None
        Pin(self._pin_num, Pin.OUT, value=0)

    def tone(self, freq, duration_ms):
        """Blocking beep."""
        self.start(freq)
        time.sleep_ms(duration_ms)
        self.stop()
