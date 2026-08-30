import time
import framebuf
import micropython
from machine import Pin

MADCTL_MY = 0x80
MADCTL_MX = 0x40
MADCTL_MV = 0x20
MADCTL_ML = 0x10
MADCTL_BGR = 0x08
MADCTL_MH = 0x04
MADCTL_RGB = 0x00

ROTATIONS_128 = [
    (0x00, 128, 128),
    (0x60, 128, 128),
    (0xC0, 128, 128),
    (0xA0, 128, 128),
]

def color565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

@micropython.viper
def _draw_text_viper(dst_buf: ptr8, dst_w: int, dst_h: int, src_buf: ptr8, src_w: int, src_h: int, start_x: int, start_y: int, size: int, hi: int, lo: int):
    stride = dst_w * 2
    for sy in range(src_h):
        row_offset = sy * src_w * 2
        for sx in range(src_w):
            idx = row_offset + (sx << 1)
            if src_buf[idx] != 0 or src_buf[idx + 1] != 0:
                dx = start_x + sx * size
                dy = start_y + sy * size
                for py in range(size):
                    cury = dy + py
                    if cury >= 0 and cury < dst_h:
                        for px in range(size):
                            curx = dx + px
                            if curx >= 0 and curx < dst_w:
                                d = cury * stride + (curx << 1)
                                dst_buf[d] = hi
                                dst_buf[d + 1] = lo

@micropython.viper
def _blit_viper(dst_buf: ptr8, dst_w: int, dst_h: int, swapped: ptr8, w: int, h: int, x: int, y: int, key: int, has_key: int):
    dst_stride = dst_w << 1
    src_stride = w << 1
    key_hi = (key >> 8) & 0xFF
    key_lo = key & 0xFF

    for sy in range(h):
        dy = y + sy
        if dy >= 0 and dy < dst_h:
            s_row = sy * src_stride
            d_row = dy * dst_stride
            for sx in range(w):
                dx = x + sx
                if dx >= 0 and dx < dst_w:
                    s_idx = s_row + (sx << 1)
                    b0 = swapped[s_idx]
                    b1 = swapped[s_idx + 1]
                    if has_key == 1 and ((b0 << 8) | b1) == key:
                        continue
                    d_idx = d_row + (dx << 1)
                    dst_buf[d_idx] = b0
                    dst_buf[d_idx + 1] = b1

@micropython.viper
def _fillrect_viper(dst_buf: ptr8, dst_w: int, dst_h: int, x0: int, y0: int, x1: int, y1: int, hi: int, lo: int):
    stride = dst_w << 1
    for yy in range(y0, y1 + 1):
        off = yy * stride
        for xx in range(x0, x1 + 1):
            idx = off + (xx << 1)
            dst_buf[idx] = hi
            dst_buf[idx + 1] = lo

class ST7735:
    NOP = 0x00
    SLPOUT = 0x11
    NORON = 0x13
    INVOFF = 0x20
    INVON = 0x21
    DISPON = 0x29
    CASET = 0x2A
    RASET = 0x2B
    RAMWR = 0x2C
    COLMOD = 0x3A
    MADCTL = 0x36

    BLACK = 0
    WHITE = color565(0xFF, 0xFF, 0xFF)
    RED = color565(0xFF, 0x00, 0x00)
    GREEN = color565(0x00, 0xFF, 0x00)
    BLUE = color565(0x00, 0x00, 0xFF)
    YELLOW = color565(0xFF, 0xFF, 0x00)
    CYAN = color565(0x00, 0xFF, 0xFF)
    GRAY = color565(0x80, 0x80, 0x80)

    def __init__(self, spi, dc, reset, cs=None, width=128, height=128, bgr=True, x_offset=0, y_offset=0):
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
        self._win_buf = bytearray(4)
        self.buf = bytearray(self.width * self.height * 2)
        self._fb = framebuf.FrameBuffer(self.buf, self.width, self.height, framebuf.RGB565)

        self.dc.init(mode=Pin.OUT, value=1)
        if self.cs:
            self.cs.init(mode=Pin.OUT, value=1)
        if self.reset_pin:
            self.reset_pin.init(mode=Pin.OUT, value=1)

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
        base, w, h = ROTATIONS_128[self.rotation]
        mode = MADCTL_BGR if not self.rgb_mode else MADCTL_RGB
        self._cmd(self.MADCTL)
        self._data(bytearray([base | mode]))

    def _apply_rotation_dims(self, rot):
        old_w, old_h = self.width, self.height
        base, base_w, base_h = ROTATIONS_128[rot]
        want_w, want_h = (base_h, base_w) if (rot & 1) else (base_w, base_h)
        if (old_w, old_h) != (want_w, want_h):
            self.width, self.height = want_w, want_h
            self.buf = bytearray(self.width * self.height * 2)
            self._fb = framebuf.FrameBuffer(self.buf, self.width, self.height, framebuf.RGB565)
        if (self.rotation ^ rot) & 1:
            self.x_offset, self.y_offset = self.y_offset, self.x_offset

    def set_rotation(self, rot):
        rot &= 3
        self._apply_rotation_dims(rot)
        self.rotation = rot
        self._madctl()

    def init(self, rotation=0):
        if self.reset_pin:
            self.reset_pin(1)
            time.sleep_ms(50)
            
        self._cmd(self.SLPOUT)
        time.sleep_ms(120)

        self._cmd(self.NORON)
        time.sleep_ms(10)

        self._apply_rotation_dims(rotation & 3)
        self.rotation = rotation & 3
        self._madctl()

        self._cmd(self.COLMOD)
        self._data(b"\x05")

        self._cmd(self.INVOFF)
        self._cmd(self.DISPON)
        time.sleep_ms(120)

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

    def commit(self):
        self._set_window(0, 0, self.width - 1, self.height - 1)
        self.dc(1)
        if self.cs:
            self.cs(0)
            
        self.spi.write(self.buf)
            
        if self.cs:
            self.cs(1)
            
        self._cmd(self.NOP)

    def blit(self, fbuf, x, y, key=-1, palette=None):
        w = getattr(fbuf, "width", None)
        h = getattr(fbuf, "height", None)
        if w is None or h is None:
            return

        scratch_buf = bytearray(w * h * 2)
        scratch = framebuf.FrameBuffer(scratch_buf, w, h, framebuf.RGB565)
        if key != -1:
            scratch.fill(key)
        scratch.blit(fbuf, 0, 0, key, palette)

        swapped = bytearray(len(scratch_buf))
        swapped[0::2] = scratch_buf[1::2]
        swapped[1::2] = scratch_buf[0::2]

        has_key = 0 if key == -1 else 1
        k_val = 0 if key == -1 else key
        _blit_viper(self.buf, self.width, self.height, swapped, w, h, x, y, k_val, has_key)

    def pixel(self, x, y, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            i = (y * self.width + x) * 2
            self.buf[i] = color >> 8
            self.buf[i + 1] = color & 0xFF

    def fillrect(self, x, y, w, h, color):
        x0 = clamp(x, 0, self.width)
        y0 = clamp(y, 0, self.height)
        x1 = clamp(x + w - 1, 0, self.width - 1)
        y1 = clamp(y + h - 1, 0, self.height - 1)
        if x1 < x0 or y1 < y0:
            return

        hi = color >> 8
        lo = color & 0xFF
        _fillrect_viper(self.buf, self.width, self.height, x0, y0, x1, y1, hi, lo)

    def fill_rect(self, x, y, w, h, color):
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
        length = len(s)
        if bg is not None:
            self.fillrect(x, y, length * 8 * size, 8 * size, bg)

        src_w, src_h = length * 8, 8
        scratch = bytearray(src_w * src_h * 2)
        fb = framebuf.FrameBuffer(scratch, src_w, src_h, framebuf.RGB565)
        fb.text(s, 0, 0, 0xFFFF)

        hi = color >> 8
        lo = color & 0xFF
        _draw_text_viper(self.buf, self.width, self.height, scratch, src_w, src_h, x, y, size, hi, lo)
