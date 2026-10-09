"""Metronome extension -- lives in Settings.

Needs the working piezo driver that ships with this extension
(Clockstar_v2/piezo_mini.py, installed over the stock disabled one).

Controls: SEL start/stop, UP/DOWN change BPM (+-1, or +-5 when pressed
quickly in a row), BACK stops and returns to Settings. 4/4 bar with an
accented first beat.
"""

import time
import json

BPM_MIN = 30
BPM_MAX = 240
BEATS_PER_BAR = 4
CLICK_MS = 30
FREQ_ACCENT = 1800
FREQ_NORMAL = 1200
FAST_PRESS_MS = 350
SAVE_PATH = "metronome.json"

_bpm = 100
_running = False
_next_beat = 0
_beat = 0          # index of the beat to play next
_shown_beat = -1   # beat currently lit on screen (-1 = none)
_off_at = None
_last_press = 0


def _load():
    global _bpm
    try:
        with open(SAVE_PATH, "r") as f:
            v = json.load(f).get("bpm")
        if isinstance(v, int) and BPM_MIN <= v <= BPM_MAX:
            _bpm = v
    except (OSError, ValueError):
        pass


def _save():
    try:
        with open(SAVE_PATH, "w") as f:
            json.dump({"bpm": _bpm}, f)
    except OSError as e:
        print("metronome save error:", e)


def _period_ms():
    return 60000 // _bpm


def register(api):
    ctx = api.ctx
    piezo = ctx.piezo
    _load()

    def _click(freq):
        if hasattr(piezo, "start"):
            piezo.start(freq)
        else:
            piezo.tone(freq, CLICK_MS)

    def _silence():
        global _off_at
        _off_at = None
        if hasattr(piezo, "stop"):
            piezo.stop()

    def background(now):
        global _next_beat, _beat, _shown_beat, _off_at
        if _off_at is not None and time.ticks_diff(now, _off_at) >= 0:
            _silence()
        if not _running:
            return
        if time.ticks_diff(now, _next_beat) >= 0:
            period = _period_ms()
            if time.ticks_diff(now, _next_beat) > period:
                _next_beat = now  # fell far behind (long redraw), resync
            _click(FREQ_ACCENT if _beat == 0 else FREQ_NORMAL)
            _off_at = time.ticks_add(now, CLICK_MS)
            _shown_beat = _beat
            _beat = (_beat + 1) % BEATS_PER_BAR
            _next_beat = time.ticks_add(_next_beat, period)
            ctx.mark_dirty()

    def _start():
        global _running, _next_beat, _beat, _shown_beat
        _running = True
        _beat = 0
        _shown_beat = -1
        _next_beat = time.ticks_ms()

    def _stop():
        global _running, _shown_beat
        _running = False
        _shown_beat = -1
        _silence()

    def on_select():
        if _running:
            _stop()
        else:
            _start()

    def _change_bpm(direction):
        global _bpm, _last_press, _next_beat
        now = time.ticks_ms()
        step = 5 if time.ticks_diff(now, _last_press) < FAST_PRESS_MS else 1
        _last_press = now
        _bpm = max(BPM_MIN, min(BPM_MAX, _bpm + direction * step))
        if _running:
            _next_beat = time.ticks_add(now, _period_ms())

    def on_up():
        _change_bpm(1)

    def on_down():
        _change_bpm(-1)

    def on_exit():
        _stop()
        _save()

    def draw():
        d = ctx.display
        C = ctx.Color
        d.fill(C.Black)
        header_h = ctx.draw_header("METRONOME", badge=False)

        s = str(_bpm)
        ctx.text_2x(s, (ctx.WIDTH - len(s) * 16) // 2, header_h + 16, C.White)
        label = "BPM"
        d.text(label, (ctx.WIDTH - len(label) * 8) // 2, header_h + 36, C.White)

        size = 14
        gap = 8
        total = BEATS_PER_BAR * size + (BEATS_PER_BAR - 1) * gap
        x = (ctx.WIDTH - total) // 2
        y = header_h + 58
        for i in range(BEATS_PER_BAR):
            if i == _shown_beat:
                d.fill_rect(x, y, size, size, C.White)
            else:
                d.rect(x, y, size, size, C.White)
            x += size + gap

        state = "RUNNING" if _running else "STOPPED"
        d.text(state, (ctx.WIDTH - len(state) * 8) // 2, y + size + 8, C.White)
        ctx.draw_footer_hint("SEL go UP/DN bpm")

    api.add_screen("Metronome", draw, on_up=on_up, on_down=on_down,
                   on_select=on_select, background=background,
                   on_exit=on_exit, veille_exempt=True, in_settings=True)
