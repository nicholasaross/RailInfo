# boards.py - Hardware definition for the NMTech NM-TV-MINER v1.0 (ESP32 "SmallTV" lottery miner).
#
# Original ESP32-D0WD (Sparkle IoT XH-32S module, no PSRAM) + 1.54" 240x240 ST7789 IPS TFT
# (10-pin FPC "HD154010C10-V3"). No touch panel; a TTP223-style touch sensor hangs off the
# "TC" pad. Verified pin map (see setup_log.md / _probe_interactive.py, 2026-07-18):
#
#   Display (ST7789, SPI(1)/HSPI, mode 0): SCK=14 MOSI=13  CS=15 DC=2  RST=not wired
#   Backlight: GPIO19 (bl) + GPIO21 (pwr), BOTH ACTIVE LOW, driven LOW before init.
#   Button: BOOT = GPIO0.  Touch: "TC" capacitive pad = GPIO32.
#
# Backlight brightness (2026-07-31): the factory NMMiner firmware drives the backlight through a
# PWM/LEDC channel (a "Brightness 0-100" setting) rather than holding it hard on; a firmware dump
# confirmed the LEDC peripheral is what dims the panel. Running the bl line at constant DC (the
# original `Pin.OUT, value=0`) leaves the backlight LED string flat-out, which reads as an overly
# bright/"obvious LEDs" glare at the base of the panel. So we now PWM GPIO19 the same way: the
# line is ACTIVE LOW, so BL_BRIGHTNESS=100 == pin held low == full on (the old behaviour), and
# lower values pulse it to dim. GPIO21 (pwr) stays a plain held-low power enable.
#
# Same strip-blit renderer as the CYD; only the driver (ST7789) and geometry (240x240) differ.

from machine import Pin, SPI, PWM
from time import sleep_ms

from st7789 import ST7789, ROTATION_0

# Backlight brightness, percent 0-100. 100 reproduces the original hard-on DC drive; lower dims
# the panel (and tames the "obvious LEDs" glare). Tune this to taste, then re-deploy.
BL_BRIGHTNESS = 90
BL_FREQ_HZ = 1000        # PWM frequency; >~200Hz is flicker-free to the eye

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


_backlight = None   # PWM handle, kept alive at module scope so it doesn't get GC'd


def _duty_u16(percent):
    """Active-low backlight: brightness == fraction of time LOW == 1 - high_fraction."""
    percent = 0 if percent < 0 else (100 if percent > 100 else percent)
    return round(65535 * (1.0 - percent / 100.0))


def set_backlight(percent):
    """Set backlight brightness (0-100) by PWMing the active-low bl line. Lazily starts PWM."""
    global _backlight
    if _backlight is None:
        _backlight = PWM(Pin(NMTV["bl"]), freq=BL_FREQ_HZ)
    _backlight.duty_u16(_duty_u16(percent))


def init_display():
    """Power the panel + backlight (both active-low, BEFORE init), then init the TFT and switch
    the backlight to PWM at BL_BRIGHTNESS. Returns (display, board_dict)."""
    b = NMTV
    Pin(b["pwr"], Pin.OUT, value=0)
    Pin(b["bl"], Pin.OUT, value=0)        # full-on during the proven init sequence
    sleep_ms(300)                         # let the gated panel rail settle before talking to it
    spi = SPI(b["spi_id"], baudrate=b["baudrate"], polarity=0, phase=0,
              sck=Pin(b["sck"]), mosi=Pin(b["mosi"]), miso=Pin(b["miso"]))
    display = ST7789(
        spi,
        cs=Pin(b["cs"]), dc=Pin(b["dc"]), rst=None,
        width=b["width"], height=b["height"], rotation=b["rotation"],
        xoff=b["xoff"], yoff=b["yoff"],
    )
    set_backlight(BL_BRIGHTNESS)          # hand the bl line to PWM once the panel is up
    return display, b
