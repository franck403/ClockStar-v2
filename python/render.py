"""
render.py -- shared low-level drawing primitives.

Pure drawing helpers that take a `display` object and `Color`/color
values as arguments -- no screen/app state lives here. Pulled out of
main.py so screens can share these without main.py being the only place
that knows how to draw a rounded rect or a 2x-scaled string.

Usage from main.py or any screen module:
    import render
    render.draw_round_rect(display, x, y, w, h, r, color)
"""

import framebuf

DISPLAY_FRAMEBUF_FORMAT = framebuf.RGB565


def draw_round_rect(display, x, y, w, h, r, color, fill=True, bg_color=None):
    r = max(0, min(r, w // 2, h // 2))

    if not fill:
        draw_round_rect(display, x, y, w, h, r, color, fill=True)
        if bg_color is not None:
            draw_round_rect(display, x + 1, y + 1, w - 2, h - 2, max(0, r - 1), bg_color, fill=True)
        return

    display.fill_rect(x + r, y, w - 2 * r, h, color)
    display.fill_rect(x, y + r, w, h - 2 * r, color)

    if r <= 0:
        return

    for row in range(r):
        dy = r - row
        seg_w = int(round((r * r - dy * dy) ** 0.5))
        if seg_w <= 0:
            continue

        display.fill_rect(x + r - seg_w, y + row, seg_w, 1, color)
        display.fill_rect(x + w - r, y + row, seg_w, 1, color)
        display.fill_rect(x + r - seg_w, y + h - 1 - row, seg_w, 1, color)
        display.fill_rect(x + w - r, y + h - 1 - row, seg_w, 1, color)


# Scratch buffer for text_2x, allocated ONCE at import time and reused on
# every call instead of a fresh bytearray per frame. This board runs very
# tight on RAM (fragmented heap, "largest free block" seen as low as ~740
# bytes in the field) -- a per-frame allocation here, happening every
# minute on the clock screen, was landing right when the heap was most
# fragmented and appears to have been enough to destabilize rendering
# (screen going blank after the first frame). Pre-allocating avoids the
# allocation entirely for the common case.
_SCRATCH_MAX_CHARS = 24  # assez pour toutes les chaines 2x utilisees dans l'app
_scratch_buf = bytearray(_SCRATCH_MAX_CHARS * 8 * 8 * 2)


def text_2x(display, s, x, y, color):
    """Draw text at 2x scale: render into a reusable scratch framebuffer at
    normal size, then blit each lit pixel as a 2x2 block."""
    src_w, src_h = len(s) * 8, 8
    needed = src_w * src_h * 2
    if needed > len(_scratch_buf):
        # Chaine plus longue que prevu -- degrade proprement au lieu de planter.
        s = s[:_SCRATCH_MAX_CHARS]
        src_w = len(s) * 8
        needed = src_w * src_h * 2

    fb = framebuf.FrameBuffer(memoryview(_scratch_buf)[:needed], src_w, src_h, DISPLAY_FRAMEBUF_FORMAT)
    fb.fill(0)
    fb.text(s, 0, 0, color)

    for sy in range(src_h):
        for sx in range(src_w):
            p = fb.pixel(sx, sy)
            if p:
                display.fill_rect(x + sx * 2, y + sy * 2, 2, 2, color)


def draw_progress_bar(display, x, y, w, h, frac, color):
    frac = 0.0 if frac < 0 else (1.0 if frac > 1.0 else frac)
    display.rect(x, y, w, h, color)
    inner_w = max(0, w - 4)
    fill_w = int(inner_w * frac)
    if fill_w > 0:
        display.fill_rect(x + 2, y + 2, fill_w, h - 4, color)


def truncate(s, max_chars):
    return s if len(s) <= max_chars else s[:max_chars - 1] + "."


def wrap_text(text, max_chars):
    words = text.split(" ")
    lines = []
    current_line = ""

    for word in words:
        while len(word) > max_chars:
            if current_line:
                lines.append(current_line)
                current_line = ""
            lines.append(word[:max_chars])
            word = word[max_chars:]

        if not word:
            continue

        if not current_line:
            current_line = word
        elif len(current_line) + 1 + len(word) <= max_chars:
            current_line += " " + word
        else:
            lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def draw_chevron(display, color, cx, cy, direction="right", size=6):
    for i in range(size):
        if direction == "right":
            display.fill_rect(cx - (size - i), cy - i, 1, 1, color)
            display.fill_rect(cx - (size - i), cy + i, 1, 1, color)
        else:
            display.fill_rect(cx + (size - i), cy - i, 1, 1, color)
            display.fill_rect(cx + (size - i), cy + i, 1, 1, color)