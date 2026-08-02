# st7789.py - PARALLEL (8-bit i8080) ST7789 driver for the Luckyminer LV02.
#
# The LV02 is a LilyGo T-Display-S3 clone: a 170x320 ST7789 wired to an 8-bit parallel bus
# (NOT SPI). Same tiny interface as the NM-TV/CYD SPI drivers - init + block()/fill_rectangle()/
# clear() + color565() - so the RailInfo strip-blit renderer is a drop-in.
#
# Verified pinout (T-Display-S3): POWER_ON=15 BL=38 CS=6 DC=7 RST=5 WR=8 RD=9
#   data D0..D7 = 39,40,41,42,45,46,47,48  (GPIO43/44 skipped - they're UART0).
# Speed: the data bus + WR strobe are driven via machine.mem32 to the S3 GPIO registers, and the
# hot pixel loops are @micropython.viper, so a full-screen push is well under a second.

import machine
from machine import Pin, mem32
from time import sleep_ms
from micropython import const
from array import array

# --- S3 GPIO registers ---
_OUT0     = const(0x60004004)   # pins 0-31 direct
_OUT0_SET = const(0x60004008)   # W1TS
_OUT0_CLR = const(0x6000400C)   # W1TC
_OUT1     = const(0x60004010)   # pins 32-53 direct

# --- ST7789 commands ---
_SWRESET = const(0x01); _SLPOUT = const(0x11); _NORON = const(0x13)
_INVOFF = const(0x20); _INVON = const(0x21); _DISPON = const(0x29)
_CASET = const(0x2A); _RASET = const(0x2B); _RAMWR = const(0x2C)
_MADCTL = const(0x36); _COLMOD = const(0x3A)

MADCTL_MY = const(0x80); MADCTL_MX = const(0x40); MADCTL_MV = const(0x20); MADCTL_BGR = const(0x08)
ROTATION_0 = const(0x00)

# Data bus D0..D7 -> OUT1 bit positions (GPIO-32). 39..42 -> 7..10, 45..48 -> 13..16.
_DBITS = (7, 8, 9, 10, 13, 14, 15, 16)
_DMASK = 0
for _b in _DBITS:
    _DMASK |= (1 << _b)          # 0x1E780


def _make_lut():
    lut = array('I', bytearray(256 * 4))
    for byte in range(256):
        v = 0
        for i in range(8):
            if byte & (1 << i):
                v |= (1 << _DBITS[i])
        lut[byte] = v
    return lut


@micropython.viper
def _blit(buf: ptr8, n: int, lut: ptr32, keep: int, wrb: int):
    out1 = ptr32(uint(0x60004010))
    clr = ptr32(uint(0x6000400C))
    setr = ptr32(uint(0x60004008))
    i = 0
    while i < n:
        out1[0] = keep | int(lut[int(buf[i])])
        clr[0] = wrb
        setr[0] = wrb
        i += 1


@micropython.viper
def _fill(n: int, hi: int, lo: int, keep: int, wrb: int):
    out1 = ptr32(uint(0x60004010))
    clr = ptr32(uint(0x6000400C))
    setr = ptr32(uint(0x60004008))
    i = 0
    while i < n:
        out1[0] = keep | hi
        clr[0] = wrb; setr[0] = wrb
        out1[0] = keep | lo
        clr[0] = wrb; setr[0] = wrb
        i += 1


class ST7789:
    def __init__(self, *, power, bl, cs, dc, rst, wr, rd, data,
                 width=320, height=170, rotation=0x60, xoff=0, yoff=35,
                 swap=True, inversion=True):
        self.width = width
        self.height = height
        self._rot = rotation
        self._xoff = xoff
        self._yoff = yoff
        # swap=True (landscape, MADCTL MV set): the wide axis (x, up to 319) must go to RASET,
        # the narrow glass axis (y, +offset) to CASET - otherwise x overflows CASET's 240 range.
        self._swap = swap
        self._inv = inversion
        self._lut = _make_lut()
        self._wrb = 1 << wr
        self._csb = 1 << cs
        self._dcb = 1 << dc
        self._rstb = 1 << rst
        # init every pin as output
        for gp in (power, bl, cs, dc, rst, wr, rd) + tuple(data):
            Pin(gp, Pin.OUT, value=0)
        Pin(rd, Pin.OUT, value=1)      # RD idle high (write-only bus)
        Pin(wr, Pin.OUT, value=1)
        Pin(cs, Pin.OUT, value=1)
        Pin(dc, Pin.OUT, value=1)
        Pin(power, Pin.OUT, value=1)   # panel power on
        Pin(bl, Pin.OUT, value=1)      # backlight on
        sleep_ms(120)
        self._reset()
        self._init_display()
        self.clear()

    # --- low-level i8080 ---
    def _w8(self, b):
        keep = mem32[_OUT1] & ~_DMASK
        mem32[_OUT1] = keep | self._lut[b]
        mem32[_OUT0_CLR] = self._wrb
        mem32[_OUT0_SET] = self._wrb

    def _cmd(self, c):
        mem32[_OUT0_CLR] = self._dcb          # DC low = command
        mem32[_OUT0_CLR] = self._csb
        self._w8(c)
        mem32[_OUT0_SET] = self._csb

    def _data(self, *bs):
        mem32[_OUT0_SET] = self._dcb          # DC high = data
        mem32[_OUT0_CLR] = self._csb
        for b in bs:
            self._w8(b)
        mem32[_OUT0_SET] = self._csb

    def _reset(self):
        mem32[_OUT0_SET] = self._rstb; sleep_ms(10)
        mem32[_OUT0_CLR] = self._rstb; sleep_ms(20)
        mem32[_OUT0_SET] = self._rstb; sleep_ms(130)

    def _init_display(self):
        self._cmd(_SLPOUT); sleep_ms(120)
        self._cmd(_COLMOD); self._data(0x55)
        self._cmd(_MADCTL); self._data(self._rot)
        self._cmd(_INVON if self._inv else _INVOFF)
        self._cmd(_NORON)
        self._cmd(_DISPON); sleep_ms(20)

    def _window(self, x0, y0, x1, y1):
        if self._swap:
            # CASET <- y (narrow glass axis, +yoff);  RASET <- x (wide axis, +xoff)
            ca0 = y0 + self._yoff; ca1 = y1 + self._yoff
            ra0 = x0 + self._xoff; ra1 = x1 + self._xoff
        else:
            ca0 = x0 + self._xoff; ca1 = x1 + self._xoff
            ra0 = y0 + self._yoff; ra1 = y1 + self._yoff
        self._cmd(_CASET); self._data(ca0 >> 8, ca0 & 0xFF, ca1 >> 8, ca1 & 0xFF)
        self._cmd(_RASET); self._data(ra0 >> 8, ra0 & 0xFF, ra1 >> 8, ra1 & 0xFF)
        self._cmd(_RAMWR)

    def block(self, x0, y0, x1, y1, buf):
        """Push a big-endian RGB565 buffer to [x0..x1]x[y0..y1] inclusive."""
        self._window(x0, y0, x1, y1)
        mem32[_OUT0_SET] = self._dcb
        mem32[_OUT0_CLR] = self._csb
        keep = mem32[_OUT1] & ~_DMASK
        _blit(buf, len(buf), self._lut, keep, self._wrb)
        mem32[_OUT0_SET] = self._csb

    def fill_rectangle(self, x, y, w, h, color565):
        if w <= 0 or h <= 0:
            return
        self._window(x, y, x + w - 1, y + h - 1)
        mem32[_OUT0_SET] = self._dcb
        mem32[_OUT0_CLR] = self._csb
        keep = mem32[_OUT1] & ~_DMASK
        hi = self._lut[color565 >> 8]
        lo = self._lut[color565 & 0xFF]
        _fill(w * h, hi, lo, keep, self._wrb)
        mem32[_OUT0_SET] = self._csb

    def clear(self, color565=0x0000):
        self.fill_rectangle(0, 0, self.width, self.height, color565)


def color565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
