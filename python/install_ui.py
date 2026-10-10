"""On-watch progress screen shown by the web installer while files are copied.

Standalone on purpose:
  * no import of the Clockstar_v2 package (it does not exist yet on a fresh watch),
  * no full framebuffer: everything is drawn in small bands (<= 4 KB), so it can
    not fragment the heap the way the full UI does,
  * every hardware constant is right below, taken from the Clockstar 2.0 schematic.

Raw-REPL API used by index.html:
    import install_ui as ui
    ui.begin(total_files)                 # prints 'UI_OK <battery %> <usb 0/1> <battery mV>'
    ui.update(pct, 'main.py', n, total)   # optional: title='Speed test', msg='...'
    ui.done('Restarting...')
    ui.fail('short reason')
"""
import gc
import time
import framebuf
from machine import ADC, Pin, SPI

# ---- hardware (Clockstar 2.0 schematic, U1 = ESP32-S3-MINI-1) ----
SPI_ID = 2
PIN_SCK, PIN_MOSI, PIN_DC, PIN_RST = 48, 34, 33, 47
PIN_BL = 9          # TFT_BL, active LOW (PMOS switch)
PIN_BATT = 10       # BATT_READ (IO10): BATT -> 3x20k / 20k divider = x4, ADC1
PIN_USB = 36        # USB_DETECT (IO36): VBUS divider, 1 = USB power present
BATT_FACTOR = 4.0
BATT_OFFSET_MV = 75

# ---- panel: 128x128 window, board rev 2 (same values as Clockstar_v2/__init__.py) ----
W = H = 128
X_OFF, Y_OFF = 0, 32
MADCTL = 0xC8       # MY | MX | BGR  (rotation 2)

_CURVE = ((4150, 100), (4050, 95), (3970, 90), (3900, 80), (3840, 70), (3800, 60),
          (3760, 50), (3730, 40), (3700, 30), (3670, 20), (3620, 10), (3550, 5), (3400, 0))


def _c(r, g, b):
    # RGB565, byte-swapped: framebuf stores little-endian, the panel wants big-endian
    v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return ((v & 0xFF) << 8) | (v >> 8)


BG = _c(10, 12, 20)
PANEL = _c(28, 32, 48)
TRACK = _c(40, 46, 66)
FG = _c(255, 255, 255)
DIM = _c(140, 150, 170)
ACC = _c(59, 130, 246)
OK = _c(76, 217, 100)
WARN = _c(255, 180, 0)
BAD = _c(255, 80, 70)

_spi = None
_dc = None
_rst = None
_bl = None
_adc = None
_usb = None

st = {'title': 'Installing', 'name': '', 'pct': 0, 'n': 0, 'total': 0, 'msg': '', 'col': ACC}


# ---------------------------------------------------------------- low level
def _cmd(c, d=None):
    _dc(0)
    _spi.write(bytes((c,)))
    if d is not None:
        _dc(1)
        _spi.write(d)


def _win(x0, y0, x1, y1):
    x0 += X_OFF
    x1 += X_OFF
    y0 += Y_OFF
    y1 += Y_OFF
    _cmd(0x2A, bytes((x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)))
    _cmd(0x2B, bytes((y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF)))
    _cmd(0x2C)
    _dc(1)


def rect(x, y, w, h, color):
    if x < 0:
        w += x
        x = 0
    if y < 0:
        h += y
        y = 0
    if x + w > W:
        w = W - x
    if y + h > H:
        h = H - y
    if w <= 0 or h <= 0:
        return
    row = color.to_bytes(2, 'little') * w
    _win(x, y, x + w - 1, y + h - 1)
    for _ in range(h):
        _spi.write(row)


def text(s, x, y, fg, bg, bold=False):
    """8x8 text on a solid background. Callers pad strings to a fixed width."""
    n = min(len(s), (W - x) // 8)
    if n <= 0:
        return
    s = s[:n]
    wpx = n * 8 + (1 if bold else 0)
    if x + wpx > W:
        wpx = W - x
    buf = bytearray(wpx * 8 * 2)
    fb = framebuf.FrameBuffer(buf, wpx, 8, framebuf.RGB565)
    fb.fill(bg)
    fb.text(s, 0, 0, fg)
    if bold:
        fb.text(s, 1, 0, fg)
    _win(x, y, x + wpx - 1, y + 7)
    _spi.write(buf)


def ctext(s, y, fg, bg, bold=False):
    width = 15 if bold else 16
    s = str(s)
    if len(s) > width:
        s = s[:width]
    s = s.center(width)
    wpx = width * 8 + (1 if bold else 0)
    text(s, (W - wpx) // 2, y, fg, bg, bold)


def big(s, y, fg, bg):
    """2x text, centered. Callers pass a fixed-length string."""
    n = min(len(s), 8)
    s = s[:n]
    sw = n * 8
    ow = sw * 2
    mono = bytearray(sw)
    fb = framebuf.FrameBuffer(mono, sw, 8, framebuf.MONO_HLSB)
    fb.text(s, 0, 0, 1)
    fgb = fg.to_bytes(2, 'little')
    bgb = bg.to_bytes(2, 'little')
    rowlen = ow * 2
    out = bytearray(rowlen * 16)
    for r in range(8):
        row = bytearray(bgb * ow)
        for cx in range(sw):
            if fb.pixel(cx, r):
                j = cx * 4
                row[j:j + 4] = fgb + fgb
        out[(2 * r) * rowlen:(2 * r + 1) * rowlen] = row
        out[(2 * r + 1) * rowlen:(2 * r + 2) * rowlen] = row
    x = (W - ow) // 2
    _win(x, y, x + ow - 1, y + 15)
    _spi.write(out)


# ---------------------------------------------------------------- sensors
def battery():
    """(percent, millivolts) from BATT_READ on IO10."""
    uv = 0
    for _ in range(16):
        uv += _adc.read_uv()
        time.sleep_us(200)
    mv = int(uv / 16000 * BATT_FACTOR + BATT_OFFSET_MV)
    if mv >= _CURVE[0][0]:
        return 100, mv
    if mv <= _CURVE[-1][0]:
        return 0, mv
    for i in range(len(_CURVE) - 1):
        hi_v, hi_p = _CURVE[i]
        lo_v, lo_p = _CURVE[i + 1]
        if lo_v <= mv <= hi_v:
            return int(lo_p + (mv - lo_v) * (hi_p - lo_p) / (hi_v - lo_v) + 0.5), mv
    return 0, mv


def usb():
    """1 when USB power is present (USB_DETECT on IO36)."""
    return 1 if _usb.value() else 0


# ---------------------------------------------------------------- drawing
def _header(pct, mv, u):
    rect(0, 0, W, 28, PANEL)
    text('ClockStar v2', 6, 4, FG, PANEL, True)
    col = OK if pct >= 40 else (WARN if pct >= 20 else BAD)
    rect(98, 3, 22, 10, DIM)
    rect(99, 4, 20, 8, PANEL)
    fw = pct * 18 // 100
    if fw > 0:
        rect(100, 5, fw, 6, col)
    rect(120, 6, 2, 4, DIM)
    text('USB ok' if u else 'no USB', 4, 17, OK if u else WARN, PANEL)
    text(('%d%% %d.%dV' % (pct, mv // 1000, (mv % 1000) // 100)).rjust(9), 54, 17, col, PANEL)


def _bar(frac, col):
    x, y, w, h = 4, 66, 120, 14
    rect(x, y, w, 1, DIM)
    rect(x, y + h - 1, w, 1, DIM)
    rect(x, y + 1, 1, h - 2, DIM)
    rect(x + w - 1, y + 1, 1, h - 2, DIM)
    inner = w - 4
    fw = int(inner * frac)
    if fw > 0:
        rect(x + 2, y + 2, fw, h - 4, col)
    if fw < inner:
        rect(x + 2 + fw, y + 2, inner - fw, h - 4, TRACK)


def _draw():
    pct, mv = battery()
    u = usb()
    _header(pct, mv, u)
    ctext(st['title'], 36, FG, BG, True)
    name = st['name']
    if len(name) > 16:
        name = '...' + name[-13:]
    ctext(name, 52, DIM, BG)
    p = st['pct']
    _bar(p / 100, st['col'])
    big(('%d%%' % p).center(4), 88, st['col'], BG)
    if st['msg']:
        ctext(st['msg'], 108, st['col'], BG)
    elif not u:
        ctext('LOW BATTERY!' if pct < 20 else 'Plug in USB', 108, WARN, BG)
    else:
        ctext('Do not unplug', 108, DIM, BG)
    if st['total']:
        ctext('%d/%d files' % (st['n'], st['total']), 118, DIM, BG)
    else:
        ctext('', 118, DIM, BG)
    gc.collect()


# ---------------------------------------------------------------- public API
def begin(total=0):
    global _spi, _dc, _rst, _bl, _adc, _usb
    gc.collect()
    if _spi is None:
        _spi = SPI(SPI_ID, baudrate=10000000, polarity=0, phase=0,
                   sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI))
        _dc = Pin(PIN_DC, Pin.OUT, value=1)
        _rst = Pin(PIN_RST, Pin.OUT, value=1)
        _bl = Pin(PIN_BL, Pin.OUT, value=1)
        _adc = ADC(Pin(PIN_BATT))
        _adc.atten(ADC.ATTN_2_5DB)
        _usb = Pin(PIN_USB, Pin.IN)

    _rst(1)
    time.sleep_ms(10)
    _rst(0)
    time.sleep_ms(20)
    _rst(1)
    time.sleep_ms(120)
    _cmd(0x11)                       # SLPOUT
    time.sleep_ms(120)
    _cmd(0x13)                       # NORON
    time.sleep_ms(10)
    _cmd(0x36, bytes((MADCTL,)))
    _cmd(0x3A, b'\x05')              # 16 bpp
    _cmd(0x20)                       # INVOFF
    _cmd(0x29)                       # DISPON
    time.sleep_ms(120)

    rect(0, 0, W, H, BG)
    _bl(0)                           # backlight on (active low)
    st['title'] = 'Installing'
    st['name'] = ''
    st['pct'] = 0
    st['n'] = 0
    st['total'] = total
    st['msg'] = ''
    st['col'] = ACC
    _draw()
    pct, mv = battery()
    print('UI_OK %d %d %d' % (pct, usb(), mv))


def update(pct, name='', n=0, total=None, title=None, msg=None):
    st['pct'] = max(0, min(100, int(pct)))
    st['name'] = name
    st['n'] = n
    if total is not None:
        st['total'] = total
    if title is not None:
        st['title'] = title
    if msg is not None:
        st['msg'] = msg
    _draw()


def done(msg='Restarting...'):
    st['title'] = 'Done!'
    st['name'] = ''
    st['pct'] = 100
    st['n'] = st['total']
    st['msg'] = msg
    st['col'] = OK
    _draw()


def fail(msg='See web page'):
    st['title'] = 'Failed'
    st['msg'] = msg
    st['col'] = BAD
    _draw()
