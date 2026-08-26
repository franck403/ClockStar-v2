"""Simple step counter built on the Clockstar v2's onboard gyro.

Detects steps as rising-then-falling peaks in gyro magnitude above a
threshold, with a minimum interval between counted steps to reject
double-counting from a single bounce. No accelerometer fusion -- gyro
only, since that's what's confirmed available on this BSP (cs.imu.get_gyro()).

Usage:
    import pedometer
    pedometer.poll()          # call every loop tick (or every 20-50ms)
    pedometer.get_steps()     # -> int
    pedometer.reset()

Threshold/interval are tuned constants, not calibrated against real
device data yet -- expect to adjust STEP_THRESHOLD after testing on
the actual watch (log _last_magnitude while walking vs standing still).
"""

import time

import Clockstar_v2 as cs

STEP_THRESHOLD = 9.0        # gyro magnitude peak that counts as a step
MIN_STEP_INTERVAL_MS = 250   # ~4 steps/sec max, filters noise/double-count

_step_count = 0
_rising = False
_last_step_time = 0
_last_magnitude = 0.0


def _gyro_magnitude():
    gx, gy, gz = cs.imu.get_gyro()
    return (gx * gx + gy * gy + gz * gz) ** 0.5


def poll():
    """Call every loop tick. Cheap: one gyro read + a few comparisons."""
    global _step_count, _rising, _last_step_time, _last_magnitude

    mag = _gyro_magnitude()
    now = time.ticks_ms()

    if mag > STEP_THRESHOLD and not _rising:
        _rising = True
    elif mag < STEP_THRESHOLD and _rising:
        _rising = False
        if time.ticks_diff(now, _last_step_time) >= MIN_STEP_INTERVAL_MS:
            _step_count += 1
            _last_step_time = now

    _last_magnitude = mag


def get_steps():
    return _step_count


def reset():
    global _step_count
    _step_count = 0