# boards.py - Hardware definition for the NMTech NM-TV-MINER v1.0 (ESP32 "SmallTV" lottery miner).
#
# Original ESP32-D0WD (Sparkle IoT XH-32S module, no PSRAM) + 1.54" 240x240 ST7789 IPS TFT
# (10-pin FPC "HD154010C10-V3"). No touch panel; a TTP223-style touch sensor hangs off the
# "TC" pad. IMPORTANT: this v1.0 board does NOT match NMTech's published NM-TV-154 pinout
# (that doc's "TFT_BL 19"/"TFT_PWER 21" are actually DC/CS here!). Pin map found empirically
# by interactive brute force (see setup_log.md / _probe_interactive.py, 2026-07-18):
#
#   Display (ST7789, SPI(1)/HSPI, mode 0): SCK=14 MOSI=13  DC=19 CS=21  RST=not wired
#   Backlight: hardwired on (no GPIO controls it - swept every pin).
#   Button: BOOT = GPIO0.
#
# Same strip-blit renderer as the CYD; only the driver (ST7789), geometry (240x240) and the
# absence of a backlight pin differ.

from machine import Pin, SPI
from time import sleep_ms

from st7789 import ST7789, ROTATION_0

NMTV = {
    "spi_id": 1, "baudrate": 20_000_000,  # HSPI native SCK/MOSI (14/13); 20MHz verified on-panel
    "sck": 14, "mosi": 13, "miso": 34,    # panel has no MISO; 34 (input-only) parks the bus input
    "cs": 15, "dc": 2, "rst": None,       # documented map, verified 2026-07-18
    # BOTH backlight pins are ACTIVE LOW and must be driven LOW BEFORE the panel init or
    # nothing is ever visible (this cost a whole day of phantom-pin chasing - see setup_log.md):
    "bl": 19, "pwr": 21,
    "button": 0,                          # BOOT (footprint may be unpopulated; TC touch is primary)
    # The "TC" pad is a bare capacitive plate on GPIO32, read via machine.TouchPad (ESP32's own
    # touch peripheral - there is no sensor chip). Baseline ~864, touching drops it ~190.
    "touch": 32,
    "width": 240, "height": 240,
    "rotation": ROTATION_0,   # 0x00 verified: RGB order, white marker top-left, no offsets
    "xoff": 0, "yoff": 0,
}


def init_display():
    """Power the panel + backlight (both active-low, BEFORE init), then init the TFT.
    Returns (display, board_dict)."""
    b = NMTV
    Pin(b["pwr"], Pin.OUT, value=0)
    Pin(b["bl"], Pin.OUT, value=0)
    sleep_ms(300)                         # let the gated panel rail settle before talking to it
    spi = SPI(b["spi_id"], baudrate=b["baudrate"], polarity=0, phase=0,
              sck=Pin(b["sck"]), mosi=Pin(b["mosi"]), miso=Pin(b["miso"]))
    display = ST7789(
        spi,
        cs=Pin(b["cs"]), dc=Pin(b["dc"]), rst=None,
        width=b["width"], height=b["height"], rotation=b["rotation"],
        xoff=b["xoff"], yoff=b["yoff"],
    )
    return display, b
