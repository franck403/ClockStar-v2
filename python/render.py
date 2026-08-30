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


def text_2x(display, s, x, y, color):
    """Draw text at 2x scale: render into a scratch framebuffer at normal
    size, then blit each row as runs of contiguous lit pixels (one
    fill_rect per run) instead of one fill_rect per pixel.

    The old version called fb.pixel() + display.fill_rect() once for
    EVERY pixel in the src_w x src_h scratch buffer (e.g. 320 calls for
    a 5-char string) -- each fill_rect is itself an SPI/framebuf write,
    so that's hundreds of Python-level calls per draw. Real 8x8 bitmap
    fonts are mostly horizontal runs (strokes), so collapsing each row
    into runs cuts the call count by roughly the average run length --
    typically 5-15x fewer fill_rect calls for normal text.
    """
    src_w, src_h = len(s) * 8, 8
    fb = framebuf.FrameBuffer(
        bytearray(
            src_w * src_h * 2 if DISPLAY_FRAMEBUF_FORMAT == framebuf.RGB565
            else (src_w * src_h + 7) // 8
        ),
        src_w, src_h, DISPLAY_FRAMEBUF_FORMAT,
    )
    fb.text(s, 0, 0, color)
    for sy in range(src_h):
        run_start = -1
        for sx in range(src_w):
            lit = fb.pixel(sx, sy)
            if lit:
                if run_start == -1:
                    run_start = sx
            else:
                if run_start != -1:
                    display.fill_rect(x + run_start * 2, y + sy * 2, (sx - run_start) * 2, 2, color)
                    run_start = -1
        if run_start != -1:
            display.fill_rect(x + run_start * 2, y + sy * 2, (src_w - run_start) * 2, 2, color)


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
