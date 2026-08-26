import time
from machine import ADC, Pin

BATTERY_PIN = 8
adc = ADC(Pin(BATTERY_PIN))
adc.atten(ADC.ATTN_11DB)

VOLTAGE_DIVIDER_RATIO = 2.0
TOTAL_CAPACITY_MAH = 600

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


def get_battery_voltage():
    uv_sum = 0
    for _ in range(32):
        uv_sum += adc.read_uv()
        time.sleep_us(100)
    uv_avg = uv_sum / 32.0

    measured_v = uv_avg / 1_000_000.0
    return measured_v * VOLTAGE_DIVIDER_RATIO


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
    CHARGE_PIN = 36
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

