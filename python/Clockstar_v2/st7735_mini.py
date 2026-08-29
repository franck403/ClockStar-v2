# Driver ST7735 minimal (fill / pixel / rect / line / circle / texte)
# Pas de dependance externe, pas de @micropython.native, RAM/flash reduits.

import time
from machine import Pin

# MADCTL rotation bits (regarder l'ecran pins en haut)
ROTATIONS = [0x00, 0x60, 0xC0, 0xA0]
BGR = 0x08
RGB = 0x00

# Police par defaut : 5x7, 1bpp, colonnes (font["Data"] = bytes, une colonne par byte)
# ASCII 32-126. Remplace ce dict par ta propre police si besoin.
DEFAULT_FONT = {
    "Width": 5,
    "Height": 7,
    "Start": 32,
    "End": 126,
    "Data": b"",  # a completer avec les donnees de police reelles
}


def color565(r, g, b):
    """RGB 0-255 -> couleur 16 bits (565)."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


class ST7735:
    # Commandes
    SWRESET = 0x01
    SLPOUT = 0x11
    INVOFF = 0x20
    INVON = 0x21
    DISPON = 0x29
    DISPOFF = 0x28
    CASET = 0x2A
    RASET = 0x2B
    RAMWR = 0x2C
    COLMOD = 0x3A
    MADCTL = 0x36
    FRMCTR1 = 0xB1
    INVCTR = 0xB4
    PWCTR1 = 0xC0
    PWCTR2 = 0xC1
    PWCTR3 = 0xC2
    PWCTR4 = 0xC3
    PWCTR5 = 0xC4
    VMCTR1 = 0xC5
    GMCTRP1 = 0xE0
    GMCTRN1 = 0xE1
    NORON = 0x13

    BLACK = 0
    WHITE = color565(0xFF, 0xFF, 0xFF)
    RED = color565(0xFF, 0x00, 0x00)
    GREEN = color565(0x00, 0xFF, 0x00)
    BLUE = color565(0x00, 0x00, 0xFF)
    YELLOW = color565(0xFF, 0xFF, 0x00)
    CYAN = color565(0x00, 0xFF, 0xFF)
    GRAY = color565(0x80, 0x80, 0x80)

    def __init__(self, spi, dc, reset, cs=None, width=128, height=128,
                 bgr=True, x_offset=0, y_offset=0, font=None):
        self.spi = spi
        self.dc = dc
        self.reset_pin = reset
        self.cs = cs
        self.width = width
        self.height = height
        self.rgb_mode = not bgr
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.rotation = 0
        self._color_buf = bytearray(2)
        self._win_buf = bytearray(4)
        self.font = font or DEFAULT_FONT

    # ---- bas niveau ----

    def _cmd(self, c):
        self.dc(0)
        if self.cs:
            self.cs(0)
        self.spi.write(bytearray([c]))
        if self.cs:
            self.cs(1)

    def _data(self, d):
        self.dc(1)
        if self.cs:
            self.cs(0)
        self.spi.write(d if isinstance(d, (bytes, bytearray)) else bytearray(d))
        if self.cs:
            self.cs(1)

    def _madctl(self):
        mode = RGB if self.rgb_mode else BGR
        self._cmd(self.MADCTL)
        self._data(bytearray([ROTATIONS[self.rotation] | mode]))

    def _reset(self):
        if self.reset_pin is None:
            return
        self.dc(0)
        self.reset_pin(1)
        time.sleep_ms(1)
        self.reset_pin(0)
        time.sleep_ms(1)
        self.reset_pin(1)
        time.sleep_ms(1)

    def set_rotation(self, rot):
        """0-3, chaque pas = 90 degres."""
        rot &= 3
        if (self.rotation ^ rot) & 1:
            self.width, self.height = self.height, self.width
        self.rotation = rot
        self._madctl()

    def init(self, rotation=0):
        """Sequence d'init generique (compatible tags rouge/vert/bleu ST7735)."""
        self._reset()
        self._cmd(self.SWRESET)
        time.sleep_ms(150)
        self._cmd(self.SLPOUT)
        time.sleep_ms(255)

        self._cmd(self.FRMCTR1)
        self._data(bytearray([0x01, 0x2C, 0x2D]))

        self._cmd(self.INVCTR)
        self._data(bytearray([0x07]))

        self._cmd(self.PWCTR1)
        self._data(bytearray([0xA2, 0x02, 0x84]))
        self._cmd(self.PWCTR2)
        self._data(bytearray([0xC5]))
        self._cmd(self.PWCTR3)
        self._data(bytearray([0x0A, 0x00]))
        self._cmd(self.PWCTR4)
        self._data(bytearray([0x8A, 0x2A]))
        self._cmd(self.PWCTR5)
        self._data(bytearray([0x8A, 0xEE]))
        self._cmd(self.VMCTR1)
        self._data(bytearray([0x0E]))

        self._cmd(self.INVOFF)
        self.rotation = rotation
        self._madctl()

        self._cmd(self.COLMOD)
        self._data(bytearray([0x05]))  # 16 bits couleur

        self._cmd(self.GMCTRP1)
        self._data(bytearray([0x02, 0x1c, 0x07, 0x12, 0x37, 0x32, 0x29, 0x2d,
                               0x29, 0x25, 0x2b, 0x39, 0x00, 0x01, 0x03, 0x10]))
        self._cmd(self.GMCTRN1)
        self._data(bytearray([0x03, 0x1d, 0x07, 0x06, 0x2e, 0x2c, 0x29, 0x2d,
                               0x2e, 0x2e, 0x37, 0x3f, 0x00, 0x00, 0x02, 0x10]))

        self._cmd(self.NORON)
        time.sleep_ms(10)
        self._cmd(self.DISPON)
        time.sleep_ms(100)

    # ---- fenetre / dessin ----

    def _set_window(self, x0, y0, x1, y1):
        x0 += self.x_offset
        x1 += self.x_offset
        y0 += self.y_offset
        y1 += self.y_offset

        self._cmd(self.CASET)
        self._win_buf[0] = x0 >> 8
        self._win_buf[1] = x0 & 0xFF
        self._win_buf[2] = x1 >> 8
        self._win_buf[3] = x1 & 0xFF
        self._data(self._win_buf)

        self._cmd(self.RASET)
        self._win_buf[0] = y0 >> 8
        self._win_buf[1] = y0 & 0xFF
        self._win_buf[2] = y1 >> 8
        self._win_buf[3] = y1 & 0xFF
        self._data(self._win_buf)

        self._cmd(self.RAMWR)

    def pixel(self, x, y, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            self._set_window(x, y, x, y)
            self._color_buf[0] = color >> 8
            self._color_buf[1] = color & 0xFF
            self._data(self._color_buf)

    def fillrect(self, x, y, w, h, color):
        x0 = clamp(x, 0, self.width)
        y0 = clamp(y, 0, self.height)
        x1 = clamp(x + w - 1, 0, self.width - 1)
        y1 = clamp(y + h - 1, 0, self.height - 1)
        if x1 < x0 or y1 < y0:
            return

        self._set_window(x0, y0, x1, y1)
        npix = (x1 - x0 + 1) * (y1 - y0 + 1)
        cbuf = bytes([color >> 8, color & 0xFF]) * 32

        self.dc(1)
        if self.cs:
            self.cs(0)
        full, rest = divmod(npix, 32)
        for _ in range(full):
            self.spi.write(cbuf)
        if rest:
            self.spi.write(bytes([color >> 8, color & 0xFF]) * rest)
        if self.cs:
            self.cs(1)

    def fill_rect(self, x, y, w, h, color):
        """Alias de fillrect (compat framebuf-style naming)."""
        self.fillrect(x, y, w, h, color)

    def rect(self, x, y, w, h, color):
        self.fillrect(x, y, w, 1, color)
        self.fillrect(x, y + h - 1, w, 1, color)
        self.fillrect(x, y, 1, h, color)
        self.fillrect(x + w - 1, y, 1, h, color)

    def fill(self, color=BLACK):
        self.fillrect(0, 0, self.width, self.height, color)

    def hline(self, x, y, w, color):
        self.fillrect(x, y, w, 1, color)

    def vline(self, x, y, h, color):
        self.fillrect(x, y, 1, h, color)

    def line(self, x0, y0, x1, y1, color):
        if x0 == x1:
            y0, y1 = (y0, y1) if y0 <= y1 else (y1, y0)
            self.vline(x0, y0, y1 - y0 + 1, color)
            return
        if y0 == y1:
            x0, x1 = (x0, x1) if x0 <= x1 else (x1, x0)
            self.hline(x0, y0, x1 - x0 + 1, color)
            return

        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.pixel(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def circle(self, cx, cy, r, color, fill=False):
        x = r
        y = 0
        err = 0
        while x >= y:
            pts = ((cx + x, cy + y), (cx + y, cy + x), (cx - y, cy + x), (cx - x, cy + y),
                   (cx - x, cy - y), (cx - y, cy - x), (cx + y, cy - x), (cx + x, cy - y))
            if fill:
                self.hline(cx - x, cy + y, 2 * x + 1, color)
                self.hline(cx - x, cy - y, 2 * x + 1, color)
                self.hline(cx - y, cy + x, 2 * y + 1, color)
                self.hline(cx - y, cy - x, 2 * y + 1, color)
            else:
                for px, py in pts:
                    self.pixel(px, py, color)
            y += 1
            if err <= 0:
                err += 2 * y + 1
            if err > 0:
                x -= 1
                err -= 2 * x + 1

    def text(self, s, x, y, color, size=1, bg=None):
        """Texte via la police du driver (self.font), dict Width/Height/Start/End/Data (1bpp colonnes)."""
        font = self.font
        px = x
        py = y
        w = font["Width"] * size + 1
        for ch in s:
            if ch == "\n":
                py += font["Height"] * size + 1
                px = x
                continue
            self._char(px, py, ch, color, size, bg)
            px += w
            if px + w > self.width:
                py += font["Height"] * size + 1
                px = x

    def _char(self, x, y, ch, color, size, bg):
        font = self.font
        start, end = font["Start"], font["End"]
        ci = ord(ch)
        if not (start <= ci <= end):
            return
        fw, fh = font["Width"], font["Height"]
        offs = (ci - start) * fw
        col_data = font["Data"][offs:offs + fw]

        for cx, col in enumerate(col_data):
            for cy in range(fh):
                on = col & (1 << cy)
                if on:
                    if size <= 1:
                        self.pixel(x + cx, y + cy, color)
                    else:
                        self.fillrect(x + cx * size, y + cy * size, size, size, color)
                elif bg is not None:
                    if size <= 1:
                        self.pixel(x + cx, y + cy, bg)
                    else:
                        self.fillrect(x + cx * size, y + cy * size, size, size, bg)