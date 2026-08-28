from micropython import const
from machine import SPI, Pin, I2C
import efuse

from .st7735_mini import ST7735
from .piezo_mini import Piezo
from .rgb_mini import RGBLed
from .imu_mini import LSM6DS3TR
from .rtc_mini import BM8563

class Pins:
    BL = const(0)
    BATT = const(1)
    CHARGE = const(2)
    TFT_SCK = const(3)
    TFT_MOSI = const(4)
    TFT_DC = const(5)
    TFT_RST = const(6)
    I2C_SDA = const(7)
    I2C_SCL = const(8)
    LED_R = const(9)
    LED_G = const(10)
    LED_B = const(11)
    BUZZ = const(12)
    BTN_UP = const(13)
    BTN_DOWN = const(14)
    BTN_SELECT = const(15)
    BTN_BACK = const(16)

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


revision = efuse.read_rev()

spi_tft = SPI(1, baudrate=27000000, polarity=0, phase=0,
              sck=Pin(Pins.get(Pins.TFT_SCK)), mosi=Pin(Pins.get(Pins.TFT_MOSI)))

backlight = Pin(Pins.get(Pins.BL), mode=Pin.OUT, value=0)


def backlight_on():
    backlight.value(1)


def backlight_off():
    backlight.value(0)


if revision == 1:
    display = ST7735(
        spi_tft,
        dc=Pin(Pins.get(Pins.TFT_DC), Pin.OUT),
        reset=Pin(Pins.get(Pins.TFT_RST), Pin.OUT),
        width=128, height=128, bgr=True,
    )
    display.init(rotation=2)
elif revision == 2:
    display = ST7735(
        spi_tft,
        dc=Pin(Pins.get(Pins.TFT_DC), Pin.OUT),
        reset=Pin(Pins.get(Pins.TFT_RST), Pin.OUT),
        width=128, height=128, bgr=True,
        x_offset=0, y_offset=32,
    )
    display.init(rotation=0)
    display.set_rotation(2)
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
BTN_UP, BTN_DOWN, BTN_SELECT, BTN_BACK = 0, 1, 2, 3

class Color:
    BLACK = 0,
    WHITE  = display.WHITE
    RED    = display.RED
    GREEN  = display.GREEN
    BLUE   = display.BLUE
    YELLOW = display.YELLOW
    CYAN   = display.CYAN
    GRAY   = display.GRAY
    
Display.Color = Color

piezo = Piezo(Pins.get(Pins.BUZZ))
rgb = RGBLed(Pins.get(Pins.LED_R), Pins.get(Pins.LED_G), Pins.get(Pins.LED_B), inverted=True)


def begin():
    imu.begin()
    rtc.begin()
    if display:
        display.fill(ST7735.BLACK)
    backlight_on()
    buttons.scan()