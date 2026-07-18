# Device-side single-probe module for the interactive NM-TV v1.0 pin hunt (_probe_interactive.py
# drives this over raw REPL). setup() picks the SPI bus/mode and drives all other candidate pins
# HIGH (releasing the panel's active-low RESET and any enable transistors); probe() asserts one
# CS candidate, runs a minimal ST7789 init, and fills the panel white (or black).

import time
from machine import Pin, SPI

POOL = [0, 2, 4, 5, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33]
WHITE_ROW = b"\xff" * 480
BLACK_ROW = b"\x00" * 480

_spi = None
_pins = {}
_dc = None


def setup(sck, mosi, mode):
    global _spi, _pins
    if _spi is not None:
        _spi.deinit()
    for n in POOL:
        Pin(n, Pin.IN)
    others = [n for n in POOL if n not in (sck, mosi)]
    _pins = {n: Pin(n, Pin.OUT, value=1) for n in others}
    _spi = SPI(1, baudrate=20_000_000, polarity=mode >> 1, phase=mode & 1,
               sck=Pin(sck), mosi=Pin(mosi), miso=Pin(34))


def setup_sets(sck, mosi, mode, high):
    """Fresh, deterministic pin state: pins in `high` driven HIGH; every other candidate pin
    actively PULLED DOWN (not floating). DC/CS must be in `high`."""
    global _spi, _pins
    if _spi is not None:
        _spi.deinit()
    _pins = {}
    for n in POOL:
        if n in (sck, mosi):
            continue
        if n in high:
            _pins[n] = Pin(n, Pin.OUT, value=1)
        else:
            Pin(n, Pin.IN, Pin.PULL_DOWN)
    _spi = SPI(1, baudrate=20_000_000, polarity=mode >> 1, phase=mode & 1,
               sck=Pin(sck), mosi=Pin(mosi), miso=Pin(34))
    time.sleep_ms(150)   # settle after (possible) reset release before the first init


def _cmd(c, data=b""):
    _dc(0)
    _spi.write(bytes((c,)))
    if data:
        _dc(1)
        _spi.write(data)


def probe(dc, cs=None, white=True, d1=30, d2=60):
    """d1/d2: post-SWRESET / post-SLPOUT delays. Defaults are the ORIGINAL sweep timings that
    produced the confirmed hit; pass longer ones only deliberately (a 120/120 'safety' bump
    coincided with the toggle no longer working - under investigation)."""
    global _dc
    _dc = _pins[dc]
    if cs is not None:
        _pins[cs](0)
    _cmd(0x01)
    time.sleep_ms(d1)
    _cmd(0x11)
    time.sleep_ms(d2)
    _cmd(0x3A, b"\x55")
    _cmd(0x36, b"\x00")
    _cmd(0x21)
    _cmd(0x13)
    _cmd(0x29)
    _cmd(0x2A, b"\x00\x00\x00\xef")
    _cmd(0x2B, b"\x00\x00\x00\xef")
    _cmd(0x2C)
    _dc(1)
    row = WHITE_ROW if white else BLACK_ROW
    for _ in range(240):
        _spi.write(row)
    if cs is not None:
        _pins[cs](1)


def drive(n, level):
    """Drive one candidate pin to a level (it must be in the current setup()'s pin map)."""
    _pins[n](level)


def set_input(n):
    """Release one candidate pin to a floating input."""
    Pin(n, Pin.IN)


def release():
    global _spi
    if _spi is not None:
        _spi.deinit()
        _spi = None
    for n in POOL:
        Pin(n, Pin.IN)
