"""Working piezo driver (installed by the Metronome extension).

Replaces the stock Clockstar_v2/piezo_mini.py, whose tone() is disabled.
Adds non-blocking start()/stop() on top of the blocking tone(), and a
volume (0-100). Volume is the PWM duty cycle: a piezo is loudest at a 50%
duty, so 100 -> 50% duty and lower values get quieter; 0 is silent.
"""

import time
from machine import Pin, PWM


class Piezo:
    def __init__(self, pin):
        self._pin_num = pin
        self._pwm = None
        self.volume = 100
        Pin(pin, Pin.OUT, value=0)

    def set_volume(self, pct):
        self.volume = max(0, min(100, int(pct)))

    def start(self, freq, duty_u16=None):
        """Start a tone and return immediately; call stop() to end it."""
        self.stop()
        if duty_u16 is None:
            duty_u16 = (32768 * self.volume) // 100
        if duty_u16 <= 0:
            return
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
