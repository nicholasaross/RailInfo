# boards.py - Hardware definition for the Heltec Wireless Paper V1.2 (ESP32-S3).
#
# Single-board for now, but kept as a board dict + init_display factory (mirroring the
# read-only ESP/Bindicator project this client is based on) so another board could be added
# later. Pin map / SPI config from the ESP setup_log: MOSI=2, CLK=3, CS=4, DC=5, RST=6,
# BUSY=7, Vext=45; SPI @ 6 MHz.

from machine import Pin, SPI
from depg0213 import DEPG0213

HELTEC = {
    "spi_id": 1, "baudrate": 6_000_000,
    "sck": 3, "mosi": 2, "cs": 4, "dc": 5, "rst": 6, "busy": 7, "vext": 45,
    "width": 250, "height": 122,
}


def init_display():
    """Initialise the e-ink display. Returns (display, board_dict)."""
    b = HELTEC
    spi = SPI(b["spi_id"], baudrate=b["baudrate"], polarity=0, phase=0,
              sck=Pin(b["sck"]), mosi=Pin(b["mosi"]))
    display = DEPG0213(spi, cs=b["cs"], dc=b["dc"], rst=b["rst"],
                       busy=b["busy"], vext=b["vext"])
    return display, b
