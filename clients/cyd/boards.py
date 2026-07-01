# boards.py - Hardware definition for the CYD (Cheap Yellow Display, ESP32-2432S028).
#
# Original ESP32-WROOM-32 (no PSRAM) + 2.8" 320x240 ILI9341 colour TFT (SPI) + XPT2046
# resistive touch. Kept as a board dict + init_display factory, mirroring clients/heltec so a
# second panel could be added later. Pin map (verified against the CYD community pinout):
#
#   Display (ILI9341, SPI2): SCK=14 MOSI=13 MISO=12  CS=15 DC=2 RST=4   backlight=21
#   Touch   (XPT2046):       CLK=25 MOSI=32 MISO=39  CS=33  IRQ=36  (separate bus)
#   Button: BOOT = GPIO0.  Touch IRQ (GPIO36) doubles as a "tap" press source (see the client).
#
# The display is naturally 240x320 portrait; the ILI9341 ROTATION byte turns it into 320x240
# landscape. Backlight is a plain GPIO held high (no PWM dimming needed here).

from machine import Pin, SPI
from ili9341 import ILI9341, ROTATION_LANDSCAPE

CYD = {
    "spi_id": 1, "baudrate": 20_000_000,  # HSPI native pins (14/13/12/15); 40MHz garbled block writes
    "sck": 14, "mosi": 13, "miso": 12,
    "cs": 15, "dc": 2, "rst": 4, "bl": 21,
    "button": 0,
    # Touch (XPT2046) on its own SoftSPI bus. We READ the controller for pressure/coords rather
    # than using its IRQ line (GPIO36) — on this board that IRQ fires ~9x/s spuriously and a real
    # tap doesn't cleanly pull it low, so it's unusable as a button. See setup_log.md.
    "touch_sck": 25, "touch_mosi": 32, "touch_miso": 39, "touch_cs": 33,
    "width": 320, "height": 240,
    "rotation": ROTATION_LANDSCAPE,  # 0xE0 (RGB, un-mirrored landscape) — see ili9341.py notes
}


def init_display():
    """Initialise the TFT and turn the backlight on. Returns (display, board_dict)."""
    b = CYD
    Pin(b["bl"], Pin.OUT, value=1)  # backlight on
    spi = SPI(b["spi_id"], baudrate=b["baudrate"], polarity=0, phase=0,
              sck=Pin(b["sck"]), mosi=Pin(b["mosi"]), miso=Pin(b["miso"]))
    display = ILI9341(
        spi,
        cs=Pin(b["cs"]), dc=Pin(b["dc"]), rst=Pin(b["rst"]),
        width=b["width"], height=b["height"], rotation=b["rotation"],
    )
    return display, b
