from micropython import const
from machine import SPI, Pin, I2C, Signal
import efuse
from .st7735_mini import ST7735
from .piezo_mini import Piezo
from .rgb_mini import RGBLed
from .imu_mini import LSM6DS3TR
from .rtc_mini import BM8563
from .input_mini import InputGPIO


class Pins:
    BL = 0
    BATT = 1
    CHARGE = 2
    TFT_SCK = 3
    TFT_MOSI = 4
    TFT_DC = 5
    TFT_RST = 6
    I2C_SDA = 7
    I2C_SCL = 8
    LED_R = 9
    LED_G = 10
    LED_B = 11
    BUZZ = 12
    BTN_UP = 13
    BTN_DOWN = 14
    BTN_SELECT = 15
    BTN_BACK = 16
    _MAP = {
        BL: 9, BATT: 10, CHARGE: 36,
        TFT_SCK: 48, TFT_MOSI: 34, TFT_DC: 33, TFT_RST: 47,
        I2C_SDA: 4, I2C_SCL: 5,
        LED_R: 8, LED_G: 7, LED_B: 6,
        BUZZ: 11,
        BTN_UP: 40, BTN_DOWN: 38, BTN_SELECT: 39, BTN_BACK: 37,
    }

    @classmethod
    def get(cls, logical_pin):
        return cls._MAP.get(logical_pin, -1)


# kept as an alias for any old code that imports the lowercase name
pins = Pins

revision = efuse.read_rev()

spi_tft = SPI(2, baudrate=10000000, polarity=0, phase=0,
              sck=Pin(Pins.get(Pins.TFT_SCK)), mosi=Pin(Pins.get(Pins.TFT_MOSI)))


backlight = Signal(Pin(pins.get(Pins.BL), mode=Pin.OUT, value=True), invert=True)


# ---- display init ----
# st7735_mini.ST7735 is the real (from-scratch) driver: it only takes
# spi/dc/reset/cs/width/height/bgr/x_offset/y_offset -- NOT the old
# CircuitOS PanelST7735_128x128 kwargs (color_order, inversion, rotations,
# etc). Those belonged to the st7789.py wrapper we're replacing.

if revision == 1:
    display = ST7735(
        spi_tft,
        dc=Pin(Pins.get(Pins.TFT_DC), Pin.OUT),
        reset=Pin(Pins.get(Pins.TFT_RST), Pin.OUT),
        width=128, height=128, bgr=True,
    )
    display.init(rotation=0)
elif revision == 2:
    # TEMP DEBUG: rotation=0, no offset -- matches the bare-metal script
    # that was actually confirmed to show color on this exact unit
    # (MADCTL=0x08, no offset, INVOFF, 160-row window). rotation=2 +
    # y_offset=32 (the old assumption) never produced anything visible
    # despite every SPI transaction completing without error. Revert to
    # rotation=2 / y_offset=32 only after confirming this base case
    # actually lights up the screen.
    display = ST7735(
        spi_tft,
        dc=Pin(Pins.get(Pins.TFT_DC), Pin.OUT),
        reset=Pin(Pins.get(Pins.TFT_RST), Pin.OUT),
        width=128, height=128, bgr=True,
        x_offset=0, y_offset=32,
    )
    display.init(rotation=2)
else:
    display = None
    print("Unknown revision", revision)

i2c = I2C(0, sda=Pin(Pins.get(Pins.I2C_SDA)), scl=Pin(Pins.get(Pins.I2C_SCL)))
imu = LSM6DS3TR(i2c)
rtc = BM8563(i2c)

buttons = InputGPIO(
    [Pins.get(Pins.BTN_UP), Pins.get(Pins.BTN_DOWN),
     Pins.get(Pins.BTN_SELECT), Pins.get(Pins.BTN_BACK)],
    inverted=False,
)


class Buttons:
    Up = 0
    Down = 1
    Select = 2
    Back = 3


# ---- colors ----
# ST7735 (st7735_mini) already defines BLACK/WHITE/RED/GREEN/BLUE/YELLOW/
# CYAN/GRAY as class attributes computed from color565() -- these exist
# whether or not `display` got instantiated, since they live on the class,
# not the instance. Read them off the class directly so Color doesn't
# depend on `display` being non-None (revision could be unknown).

class Color:
    BLACK = ST7735.BLACK
    WHITE = ST7735.WHITE
    RED = ST7735.RED
    GREEN = ST7735.GREEN
    BLUE = ST7735.BLUE
    YELLOW = ST7735.YELLOW
    CYAN = ST7735.CYAN
    GRAY = ST7735.GRAY

    # lowercase aliases for old call sites
    Black = BLACK
    White = WHITE
    Red = RED
    Green = GREEN
    Blue = BLUE
    Yellow = YELLOW
    Cyan = CYAN
    Gray = GRAY

    @staticmethod
    def rgb(r, g, b):
        """Build an arbitrary 565 color, e.g. Color.rgb(255, 128, 0)."""
        from .st7735_mini import color565
        return color565(r, g, b)


class Display:
    Color = Color


piezo = Piezo(Pins.get(Pins.BUZZ))
rgb = RGBLed(Pins.get(Pins.LED_R), Pins.get(Pins.LED_G), Pins.get(Pins.LED_B), inverted=True)


def begin():
    imu.begin()
    rtc.begin()
    if display:
        display.fill(Color.BLACK)
        display.commit()
    backlight.on()
    buttons.scan()
