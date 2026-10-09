"""Pedometer extension -- simple step counter on the onboard gyro.

Uses the screens API (see screens.py): one background() that counts steps
and one screen that shows them. Detects steps as rising-then-falling peaks
in gyro magnitude above STEP_THRESHOLD, with a minimum interval between
counted steps to reject double-counting.

STEP_THRESHOLD is a tuned constant, not calibrated against real device data.
"""

import time

STEP_THRESHOLD = 9.0         # gyro magnitude peak that counts as a step
MIN_STEP_INTERVAL_MS = 250   # ~4 steps/sec max
DAILY_GOAL = 10000

_steps = 0
_rising = False
_last_step_time = 0
_shown_steps = -1


def get_steps():
    return _steps


def reset():
    global _steps
    _steps = 0


def register(api):
    ctx = api.ctx
    cs = ctx.cs

    def background(now):
        global _steps, _rising, _last_step_time
        gx, gy, gz = cs.imu.get_gyro()
        mag = (gx * gx + gy * gy + gz * gz) ** 0.5

        if mag > STEP_THRESHOLD and not _rising:
            _rising = True
        elif mag < STEP_THRESHOLD and _rising:
            _rising = False
            if time.ticks_diff(now, _last_step_time) >= MIN_STEP_INTERVAL_MS:
                _steps += 1
                _last_step_time = now

    def tick(now):
        global _shown_steps
        if _steps != _shown_steps:
            _shown_steps = _steps
            return True
        return False

    def draw():
        ctx.draw_background()
        header_h = ctx.draw_header("STEPS")

        s = str(_steps)
        text_y = header_h + 22
        ctx.text_2x(s, (ctx.WIDTH - len(s) * 16) // 2, text_y, ctx.Color.White)

        bar_y = text_y + 26
        ctx.draw_progress_bar(12, bar_y, ctx.WIDTH - 24, 10, _steps / DAILY_GOAL)

        goal = "%d / %d" % (_steps, DAILY_GOAL)
        ctx.display.text(goal, (ctx.WIDTH - len(goal) * 8) // 2, bar_y + 14, ctx.Color.White)
        ctx.draw_footer_hint("SEL reset steps")

    def on_select():
        reset()

    api.add_screen("Steps", draw, on_select=on_select, tick=tick,
                   background=background, order=50)
