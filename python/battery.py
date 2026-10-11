import time
from machine import ADC, Pin

# ---- Clockstar v2.4 schematic ----
# BATT_READ is IO10 (ADC1_CH9). The battery goes through RN1 (150R) and RN5
# (3 x 20k in series = 60k) into BATT_READ, which has 20k to GND:
#     V(BATT_READ) = V(BATT) * 20k / (60k + 20k + 150R)  ->  ratio ~ 4.0075
# 4.2V on the cell is only ~1.05V on the pin, so the 2.5dB range (about 0 to
# 1.25V) is enough and more accurate than 11dB.
#
# CALIB_EN (IO35) turns on Q5A, which makes the TL431 (U3) clamp the top of
# the divider to its 2.495V reference. BATT_READ then sits at a known
# 2.495V * 20k / 80k = 0.624V, whatever the battery voltage is, so reading it
# tells us how far this ADC is off and lets us correct every measurement.
# (It draws ~10 mA, so it is only switched on for a few ms.)
BATTERY_PIN = 10
CALIB_PIN = 35

adc = ADC(Pin(BATTERY_PIN))
adc.atten(ADC.ATTN_2_5DB)

VOLTAGE_DIVIDER_RATIO = (20000 + 60000 + 150) / 20000.0   # 4.0075
CALIB_REF_UV = 624000          # expected BATT_READ in calibration mode
CALIB_MIN_BATT_V = 3.0         # the TL431 needs the battery above ~2.6V
_cal_scale = 1.0               # measured-to-real correction, set by calibrate()
VOLTAGE_OFFSET_V = 0.075       # same read offset as the stock firmware

TOTAL_CAPACITY_MAH = 600

# Above this the TP4054 is finished (4.2V cell, C/10 cutoff); below the lower
# one a plugged-in watch is charging again.
FULL_VOLTAGE = 4.17
RECHARGE_VOLTAGE = 4.10

LEVEL_CRITICAL = 0
LEVEL_LOW = 1
LEVEL_HALF = 2
LEVEL_FULL = 3

LEVEL_NAMES = {
    LEVEL_CRITICAL: "CRITICAL",
    LEVEL_LOW: "LOW",
    LEVEL_HALF: "HALF",
    LEVEL_FULL: "FULL",
}

_DISCHARGE_CURVE = (
    (4.15, 100),
    (4.05, 95),
    (3.97, 90),
    (3.90, 80),
    (3.84, 70),
    (3.80, 60),
    (3.76, 50),
    (3.73, 40),
    (3.70, 30),
    (3.67, 20),
    (3.62, 10),
    (3.55, 5),
    (3.40, 0),
)

_last_level = LEVEL_FULL
_pending_level = LEVEL_FULL
_pending_count = 0
_CONFIRM_POLLS = 3


def _voltage_to_percentage(voltage):
    curve = _DISCHARGE_CURVE

    if voltage >= curve[0][0]:
        return 100.0
    if voltage <= curve[-1][0]:
        return 0.0

    for i in range(len(curve) - 1):
        v_hi, p_hi = curve[i]
        v_lo, p_lo = curve[i + 1]
        if v_lo <= voltage <= v_hi:
            if v_hi == v_lo:
                return float(p_hi)
            frac = (voltage - v_lo) / (v_hi - v_lo)
            return p_lo + frac * (p_hi - p_lo)

    return 0.0


def _read_uv(samples=32):
    uv_sum = 0
    for _ in range(samples):
        uv_sum += adc.read_uv()
        time.sleep_us(100)
    return uv_sum / float(samples)


def get_battery_voltage():
    measured_v = _read_uv() / 1_000_000.0
    return measured_v * VOLTAGE_DIVIDER_RATIO * _cal_scale + VOLTAGE_OFFSET_V


def calibrate():
    """Read the TL431 reference through the divider and store a correction
    factor for get_battery_voltage(). Returns the factor (1.0 = no change).
    Safe to call any time; leaves CALIB_EN low again."""
    global _cal_scale
    pin = None
    try:
        # only worth it when the battery can power the TL431
        if get_battery_voltage() < CALIB_MIN_BATT_V:   # (offset included, fine here)
            return _cal_scale
        pin = Pin(CALIB_PIN, Pin.OUT, value=0)
        pin.value(1)
        time.sleep_ms(30)
        measured = _read_uv(64)
        pin.value(0)
        if measured <= 0:
            return _cal_scale
        scale = CALIB_REF_UV / measured
        # a sane ADC is within a few percent; anything else is a bad reading
        if 0.9 <= scale <= 1.1:
            _cal_scale = scale
            print("battery: calibrated, scale=%.4f (ref read %d uV)" % (scale, measured))
        else:
            print("battery: calibration out of range (%.3f), ignored" % scale)
    except Exception as e:
        print("battery: calibration failed:", e)
        try:
            if pin is not None:
                pin.value(0)
        except Exception:
            pass
    return _cal_scale


def get_calibration_scale():
    return _cal_scale


def get_battery_percentage(voltage=None):
    if voltage is None:
        voltage = get_battery_voltage()
    percentage = _voltage_to_percentage(voltage)
    return max(0, min(100, int(round(percentage))))


def get_remaining_capacity_mah(pct=None):
    if pct is None:
        pct = get_battery_percentage()
    return int((pct / 100.0) * TOTAL_CAPACITY_MAH)


def _percentage_to_level(pct):
    if pct > 70:
        return LEVEL_FULL
    elif pct > 40:
        return LEVEL_HALF
    elif pct > 20:
        return LEVEL_LOW
    else:
        return LEVEL_CRITICAL


def set_initial_level():
    """Jump straight to the level the voltage says (used once at boot)."""
    global _last_level, _pending_level, _pending_count
    lvl = _percentage_to_level(get_battery_percentage())
    _last_level = lvl
    _pending_level = lvl
    _pending_count = 0
    return lvl


def poll(is_charging=False):
    global _last_level, _pending_level, _pending_count

    if is_charging:
        _last_level = LEVEL_FULL
        _pending_level = LEVEL_FULL
        _pending_count = 0
        return _last_level, False

    voltage = get_battery_voltage()
    pct = get_battery_percentage(voltage)
    candidate = _percentage_to_level(pct)

    if candidate == _last_level:
        _pending_level = candidate
        _pending_count = 0
        return _last_level, False

    if candidate == _pending_level:
        _pending_count += 1
    else:
        _pending_level = candidate
        _pending_count = 1

    if _pending_count >= _CONFIRM_POLLS:
        _last_level = candidate
        _pending_count = 0
        return _last_level, True

    return _last_level, False


if __name__ == "__main__":
    calibrate()
    CHARGE_PIN = 36   # USB_DETECT: 5V/2 when a USB cable is plugged in
    charge_pin = Pin(CHARGE_PIN, Pin.IN)

    is_charging = charge_pin.value() == 1
    v = get_battery_voltage()
    pct = get_battery_percentage(v)
    cap = get_remaining_capacity_mah(pct)
    level, changed = poll(is_charging=is_charging)

    level_str = LEVEL_NAMES.get(level, "UNKNOWN")
    status_str = "CHARGING" if is_charging else "DISCHARGING"

    print(
        "[{}] Voltage: {:.2f}V | Level: {}% ({:.0f} mAh) | Tier: {}".format(
            status_str, v, pct, cap, level_str
        )
    )


