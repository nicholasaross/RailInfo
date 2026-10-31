# boards.py - Hardware definition for the CYD Portrait unit (ESP32-2432S028), MicroPython.
#
# The same board as clients/cyd (original ESP32, no PSRAM, 2.8" TFT on SPI, CH340 USB-serial),
# but mounted PORTRAIT in a 3D-printed stand with the USB/power end at the BOTTOM and no openings
# for the buttons - so this client has one screen and no input. Pin map (as on the first two CYDs):
#
#   Display (SPI(1)/HSPI @ 20MHz): SCK=14 MOSI=13 MISO=12  CS=15 DC=2 RST=4   backlight=21
#   Rear RGB LED (active LOW):     R=4 G=16 B=17   (community pinout)
#
# GPIO4 is the driver's "rst", exactly as in the CYD client, and is also the LED's red channel
# (it idles high = off). GPIO16/17 are held high too, so the LED stays dark inside the stand.
#
# The rotation is the MADCTL byte that gives an un-mirrored 240x320 portrait with the USB end at
# the bottom. It depends on the panel variant (ILI9341 / ILI9342 / ST7789 all ship on this board),
# so it was found on this unit with _orient.py: a native-landscape panel -> 0xE0 (MV|MX|MY), RGB,
# no inversion. See setup_log.md.

from machine import Pin, SPI
from ili9341 import ILI9341, ROTATION_PORTRAIT

CYD = {
    "spi_id": 1, "baudrate": 20_000_000,  # HSPI native pins; 40MHz garbled block writes on the CYD
    "sck": 14, "mosi": 13, "miso": 12,
    "cs": 15, "dc": 2, "rst": 4, "bl": 21,
    "led_g": 16, "led_b": 17,
    "width": 240, "height": 320,
    "rotation": ROTATION_PORTRAIT,  # 0xE0 - portrait, USB end at the bottom (see ili9341.py)
    "invert": False,                # RGB panel, no display inversion (the ST7789 variant needs it)
}


def init_display():
    """Initialise the TFT and turn the backlight on. Returns (display, board_dict)."""
    b = CYD
    Pin(b["led_g"], Pin.OUT, value=1)  # rear RGB LED off (active low; red is "rst", idles high)
    Pin(b["led_b"], Pin.OUT, value=1)
    Pin(b["bl"], Pin.OUT, value=1)     # backlight on
    spi = SPI(b["spi_id"], baudrate=b["baudrate"], polarity=0, phase=0,
              sck=Pin(b["sck"]), mosi=Pin(b["mosi"]), miso=Pin(b["miso"]))
    display = ILI9341(
        spi,
        cs=Pin(b["cs"]), dc=Pin(b["dc"]), rst=Pin(b["rst"]),
        width=b["width"], height=b["height"], rotation=b["rotation"], invert=b["invert"],
    )
    return display, b
