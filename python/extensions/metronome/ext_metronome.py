"""Metronome extension -- lives in Settings.

Needs the working piezo driver that ships with this extension
(Clockstar_v2/piezo_mini.py, installed over the stock disabled one).

Metronome page: SEL start/stop, UP/DOWN change the BPM, BACK stops and
returns to Settings. Tap = +-1 (or +-5 when tapped quickly in a row); hold
UP or DOWN and it keeps going, faster after a moment. 4/4 bar with an
accented first beat.

Volume page (also in Settings): UP/DOWN change the buzzer volume in steps
of 10 (hold to keep going), SEL plays a test beep. Volume is stored with
the BPM in metronome.json.
"""

import time
import json

BPM_MIN = 30
BPM_MAX = 240
BEATS_PER_BAR = 4
CLICK_MS = 30
FREQ_ACCENT = 1800
FREQ_NORMAL = 1200
FAST_TAP_MS = 350        # taps closer than this count as "quick" (+-5)
HOLD_DELAY_MS = 450      # hold this long before auto-repeat starts
HOLD_INTERVAL_MS = 90    # time between repeats while held
HOLD_FAST_MS = 1300      # held this long -> bigger steps
SAVE_PATH = "metronome.json"

_bpm = 100
_volume = 100
_running = False
_next_beat = 0
_beat = 0          # index of the beat to play next
_shown_beat = -1   # beat currently lit on screen (-1 = none)
_off_at = None
_last_tap = 0


def _load():
    global _bpm, _volume
    try:
        with open(SAVE_PATH, "r") as f:
            data = json.load(f)
        v = data.get("bpm")
        if isinstance(v, int) and BPM_MIN <= v <= BPM_MAX:
            _bpm = v
        vol = data.get("volume")
        if isinstance(vol, int) and 0 <= vol <= 100:
            _volume = vol
    except (OSError, ValueError):
        pass


def _save():
    try:
        with open(SAVE_PATH, "w") as f:
            json.dump({"bpm": _bpm, "volume": _volume}, f)
    except OSError as e:
        print("metronome save error:", e)


def _period_ms():
    return 60000 // _bpm


class _Repeater:
    """Turns "UP/DOWN pressed" into tap + auto-repeat while held.

    apply(direction, mode): mode 0 = the initial tap, 1 = held, 2 = held a
    long time (use a bigger step).
    """

    def __init__(self, ctx, apply):
        self.ctx = ctx
        self.apply = apply
        self.active = False
        self.dir = 0
        self.t0 = 0
        self.last = 0

    def press(self, direction):
        now = time.ticks_ms()
        self.dir = direction
        self.t0 = now
        self.last = now
        self.apply(direction, 0)

    def update(self, now):
        if not self.active or self.dir == 0:
            return
        ctx = self.ctx
        btn = ctx.Buttons.Up if self.dir > 0 else ctx.Buttons.Down
        if not ctx.buttons.state(btn):
            self.dir = 0
            return
        held = time.ticks_diff(now, self.t0)
        if held < HOLD_DELAY_MS:
            return
        if time.ticks_diff(now, self.last) >= HOLD_INTERVAL_MS:
            self.last = now
            self.apply(self.dir, 2 if held >= HOLD_FAST_MS else 1)
            ctx.mark_dirty()

    def enter(self):
        self.active = True
        self.dir = 0

    def leave(self):
        self.active = False
        self.dir = 0


def register(api):
    ctx = api.ctx
    piezo = ctx.piezo
    _load()
    if hasattr(piezo, "set_volume"):
        piezo.set_volume(_volume)

    # ---------------------------------------------------------- metronome
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

    def _apply_bpm(direction, mode):
        global _bpm, _last_tap
        if mode == 0:
            now = time.ticks_ms()
            step = 5 if time.ticks_diff(now, _last_tap) < FAST_TAP_MS else 1
            _last_tap = now
        elif mode == 1:
            step = 1
        else:
            step = 5
        _bpm = max(BPM_MIN, min(BPM_MAX, _bpm + direction * step))

    bpm_rep = _Repeater(ctx, _apply_bpm)

    def background(now):
        global _next_beat, _beat, _shown_beat, _off_at
        bpm_rep.update(now)
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
        global _running, _beat, _shown_beat, _next_beat
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

    def on_enter():
        bpm_rep.enter()

    def on_exit():
        bpm_rep.leave()
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

    api.add_screen("Metronome", draw,
                   on_up=lambda: bpm_rep.press(1),
                   on_down=lambda: bpm_rep.press(-1),
                   on_select=on_select, background=background,
                   on_enter=on_enter, on_exit=on_exit,
                   veille_exempt=True, in_settings=True)

    # ------------------------------------------------------------- volume
    def _apply_volume(direction, mode):
        global _volume
        step = 10 if mode == 0 else 5
        _volume = max(0, min(100, _volume + direction * step))
        if hasattr(piezo, "set_volume"):
            piezo.set_volume(_volume)

    vol_rep = _Repeater(ctx, _apply_volume)

    def vol_background(now):
        vol_rep.update(now)

    def vol_select():
        if hasattr(piezo, "tone"):
            piezo.tone(FREQ_NORMAL, 120)

    def vol_enter():
        vol_rep.enter()

    def vol_exit():
        vol_rep.leave()
        _save()

    def vol_draw():
        d = ctx.display
        C = ctx.Color
        d.fill(C.Black)
        header_h = ctx.draw_header("VOLUME", badge=False)
        s = "%d%%" % _volume
        ctx.text_2x(s, (ctx.WIDTH - len(s) * 16) // 2, header_h + 18, C.White)
        ctx.draw_progress_bar(12, header_h + 46, ctx.WIDTH - 24, 10, _volume / 100)
        note = "Muted" if _volume == 0 else "Buzzer"
        d.text(note, (ctx.WIDTH - len(note) * 8) // 2, header_h + 64, C.White)
        ctx.draw_footer_hint("UP/DN vol SEL test")

    api.add_screen("Volume", vol_draw,
                   on_up=lambda: vol_rep.press(1),
                   on_down=lambda: vol_rep.press(-1),
                   on_select=vol_select, background=vol_background,
                   on_enter=vol_enter, on_exit=vol_exit,
                   veille_exempt=True, in_settings=True, order=101)
