# _orient.py - bring-up probe for the CYD Portrait: identify this unit's panel controller and
# find the MADCTL byte for portrait with the USB end at the bottom. Not a production file - kept
# for the next CYD whose panel variant is unknown.
#
#   mpremote connect COM7 cp _orient.py :          (with lib/ + boards.py already on the device)
#   mpremote connect COM7 exec "import _orient; _orient.ids()"     # panel ID registers
#   mpremote connect COM7 run _orient.py                            # cycle the test cards
#
# ids(): reads the ID registers over MISO at 1 MHz. ILI934x RDID4 (0xD3) -> xx 00 93 41
#   (ILI9341) / xx 00 93 42 (ILI9342). ST7789 RDDID (0x04) -> 85 85 52 after a 1-bit dummy, so
#   it is printed shifted as well.
# cycle(): shows a numbered test card for each of the 8 MADCTL MV/MX/MY combinations (BGR clear)
#   at 240x320: a white border round the full 240x320, "TOP" + an arrow at the top, red / green /
#   blue bars left to right, "USB end" at the bottom. The right card is upright and NOT mirrored,
#   with the border complete and "USB end" next to the connector. Red/blue swapped -> add BGR
#   (0x08) to the byte; white background / inverted colours -> invert=True in boards.py.

import time
import framebuf
from machine import Pin, SPI
from boards import CYD
from ili9341 import ILI9341, color565
from writer import Writer
import dotmatrix19

CANDIDATES = (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0)
ROUNDS = 30   # x 8 cards x HOLD_S ~= 20 minutes, plenty of time to watch
HOLD_S = 5
W, H = 240, 320

WHITE = color565(255, 255, 255)
AMBER = color565(255, 150, 0)
RED = color565(255, 0, 0)
GREEN = color565(0, 255, 0)
BLUE = color565(0, 0, 255)


class Strip(framebuf.FrameBuffer):
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.stride = (width + 7) // 8
        self.buf = bytearray(self.stride * height)
        super().__init__(self.buf, width, height, framebuf.MONO_HLSB)


_strip = Strip(W - 2, dotmatrix19.height() + 2)  # fits inside the 1px border
_wri = Writer(_strip, dotmatrix19, verbose=False)
_wri.set_clip(True, True, False)
_rgb = bytearray(_strip.width * _strip.height * 2)


def _display():
    for p in (CYD["led_g"], CYD["led_b"]):
        Pin(p, Pin.OUT, value=1)
    Pin(CYD["bl"], Pin.OUT, value=1)
    spi = SPI(CYD["spi_id"], baudrate=CYD["baudrate"], polarity=0, phase=0,
              sck=Pin(CYD["sck"]), mosi=Pin(CYD["mosi"]), miso=Pin(CYD["miso"]))
    return ILI9341(spi, cs=Pin(CYD["cs"]), dc=Pin(CYD["dc"]), rst=Pin(CYD["rst"]),
                   width=W, height=H, rotation=CANDIDATES[0], invert=CYD["invert"])


def _line(d, y, items, colour):
    """Draw [(x or None to centre, text), ...] into the strip and blit it at (1, y) in colour."""
    s = _strip
    s.fill(0)
    for x, text in items:
        if x is None:
            x = max(0, (s.width - _wri.stringlen(text)) // 2)
        Writer.set_textpos(s, 0, x)
        _wri.printstring(text, False)
    hi = colour >> 8
    lo = colour & 0xFF
    i = 0
    for row in range(s.height):
        base = row * s.stride
        for col in range(s.width):
            if s.buf[base + (col >> 3)] & (0x80 >> (col & 7)):
                _rgb[i] = hi
                _rgb[i + 1] = lo
            else:
                _rgb[i] = 0
                _rgb[i + 1] = 0
            i += 2
    d.block(1, y, s.width, y + s.height - 1, _rgb)


def _read_reg(d, cmd, n):
    """Read n bytes after `cmd`, at 1 MHz so the panel's (slow) read timing is met."""
    pins = dict(sck=Pin(CYD["sck"]), mosi=Pin(CYD["mosi"]), miso=Pin(CYD["miso"]))
    d.spi.init(baudrate=1_000_000, **pins)
    d.cs(0)
    d.dc(0)
    d.spi.write(bytes((cmd,)))
    d.dc(1)
    data = d.spi.read(n)
    d.cs(1)
    d.spi.init(baudrate=CYD["baudrate"], **pins)
    return data


def _hex(data):
    return " ".join("%02x" % b for b in data)


def ids(d=None):
    d = d or _display()
    rdid4 = _read_reg(d, 0xD3, 4)
    rddid = _read_reg(d, 0x04, 4)
    v = (rddid[0] << 24) | (rddid[1] << 16) | (rddid[2] << 8) | rddid[3]
    print("RDID4 0xD3:", _hex(rdid4), "  (ILI9341 = xx 00 93 41, ILI9342 = xx 00 93 42)")
    print("RDDID 0x04:", _hex(rddid), "  1-bit shifted: %06x" % ((v >> 7) & 0xFFFFFF),
          "  (ST7789 = 858552)")
    return d


def _card(d, n, madctl):
    d._write_cmd(0x36, madctl)            # the MADCTL under test
    d.fill_rectangle(0, 0, 320, 240, 0)   # black the whole glass whichever way the axes run now
    d.fill_rectangle(0, 0, 240, 320, 0)
    _line(d, 4, [(None, "TOP")], WHITE)
    for i in range(16):                   # arrow pointing at the top: triangle + shaft
        d.fill_rectangle(120 - i, 28 + i, 2 * i + 1, 1, AMBER)
    d.fill_rectangle(116, 44, 9, 20, AMBER)
    _line(d, 72, [(None, "card %d of 8" % n)], AMBER)
    _line(d, 94, [(None, "MADCTL 0x%02X" % madctl)], AMBER)
    d.fill_rectangle(20, 124, 60, 50, RED)
    d.fill_rectangle(90, 124, 60, 50, GREEN)
    d.fill_rectangle(160, 124, 60, 50, BLUE)
    _line(d, 178, [(44, "R"), (114, "G"), (184, "B")], WHITE)
    _line(d, 296, [(None, "USB end")], WHITE)
    d.fill_rectangle(0, 0, W, 1, WHITE)   # border last (the text strips sit inside it)
    d.fill_rectangle(0, H - 1, W, 1, WHITE)
    d.fill_rectangle(0, 0, 1, H, WHITE)
    d.fill_rectangle(W - 1, 0, 1, H, WHITE)


def cycle(d=None, rounds=ROUNDS):
    d = d or _display()
    for r in range(rounds):
        for n, madctl in enumerate(CANDIDATES, 1):
            print("round", r + 1, "card", n, "MADCTL 0x%02X" % madctl)
            _card(d, n, madctl)
            time.sleep(HOLD_S)
    print("done")


if __name__ == "__main__":
    cycle(ids())
