import time
from machine import Pin, PWM

# disabled
class Piezo:
    def __init__(self, pin):
        self._pin = Pin(pin, mode=Pin.OUT)

    def tone(self, freq, duration_ms):
        return
        pwm = PWM(self._pin, freq=freq, duty_u16=32768)
        time.sleep_ms(duration_ms)
        pwm.deinit()
