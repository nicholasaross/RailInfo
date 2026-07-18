# st7789.py - minimal ST7789 SPI driver for the NM-TV-154 (1.54" 240x240 IPS), MicroPython.
#
# Same deliberately tiny interface as the CYD's ili9341.py: init + block() (push a pre-built
# big-endian RGB565 buffer to a rectangle) + fill_rectangle()/clear(). No on-device text or
# shapes - the RailInfo client renders text into 1-bpp strips and colourises them itself.
#
# Panel notes (NM-TV-154, per NMTech's TFT_eSPI User_Setup):
# - ST7789 on SPI pins SCK=14 MOSI=13 CS=15 DC=2; RST is NOT wired (software reset only).
# - The controller RAM is 240x320; this 240x240 glass shows rows 0..239 at MADCTL 0x00, so
#   rotations that mirror Y (MY set) need yoff=80 to stay on-glass.
# - IPS panel -> colours are inverted relative to the ST7789 default; INVON (inversion=True)
#   gives normal colours. If a future unit renders negative, pass inversion=False.

from time import sleep_ms
from micropython import const

_SWRESET = const(0x01)
_SLPOUT = const(0x11)
_NORON = const(0x13)
_INVOFF = const(0x20)
_INVON = const(0x21)
_DISPON = const(0x29)
_CASET = const(0x2A)
_RASET = const(0x2B)
_RAMWR = const(0x2C)
_MADCTL = const(0x36)
_COLMOD = const(0x3A)

# MADCTL bits (for building a rotation byte in boards.py)
MADCTL_MY = const(0x80)
MADCTL_MX = const(0x40)
MADCTL_MV = const(0x20)
MADCTL_BGR = const(0x08)

ROTATION_0 = const(0x00)  # native portrait-ish 240x240, RGB


class ST7789:
    def __init__(self, spi, *, cs, dc, rst=None, width=240, height=240,
                 rotation=ROTATION_0, xoff=0, yoff=0, inversion=True):
        self.spi = spi
        self.cs = cs
        self.dc = dc
        self.rst = rst
        self.width = width
        self.height = height
        self._rotation = rotation
        self._xoff = xoff
        self._yoff = yoff
        self._inversion = inversion
        for p in (cs, dc):
            p.init(p.OUT, value=1)
        if rst is not None:
            rst.init(rst.OUT, value=1)
        self._reset()
        self._init_display()
        self.clear()

    # --- low-level SPI (CS framed once per logical transaction, like the ILI9341 driver) ---

    def _cmd(self, cmd):
        self.dc(0)
        self.spi.write(bytes((cmd,)))

    def _data(self, buf):
        self.dc(1)
        self.spi.write(buf)

    def _write_cmd(self, cmd, *data):
        self.cs(0)
        self._cmd(cmd)
        if data:
            self._data(bytes(data))
        self.cs(1)

    def _reset(self):
        if self.rst is None:          # NM-TV-154: no reset line -> software reset
            self._write_cmd(_SWRESET)
            sleep_ms(150)
            return
        self.rst(1); sleep_ms(50)
        self.rst(0); sleep_ms(50)
        self.rst(1); sleep_ms(150)

    def _init_display(self):
        self._write_cmd(_SLPOUT)
        sleep_ms(120)
        self._write_cmd(_COLMOD, 0x55)            # 16-bit/pixel
        self._write_cmd(_MADCTL, self._rotation)
        self._write_cmd(_INVON if self._inversion else _INVOFF)
        self._write_cmd(_NORON)
        self._write_cmd(_DISPON)
        sleep_ms(20)

    # --- windowing / blits ---

    def _window(self, x0, y0, x1, y1):
        """Set the address window (panel offsets applied) and issue RAMWR."""
        x0 += self._xoff; x1 += self._xoff
        y0 += self._yoff; y1 += self._yoff
        self._cmd(_CASET)
        self._data(bytes((x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)))
        self._cmd(_RASET)
        self._data(bytes((y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF)))
        self._cmd(_RAMWR)

    def block(self, x0, y0, x1, y1, buf):
        """Push a pre-built RGB565 (big-endian, 2 bytes/pixel) buffer to the rectangle
        [x0..x1] x [y0..y1] inclusive. len(buf) must be (x1-x0+1)*(y1-y0+1)*2."""
        self.cs(0)
        self._window(x0, y0, x1, y1)
        self._data(buf)
        self.cs(1)

    def fill_rectangle(self, x, y, w, h, color565):
        """Fill a rectangle with a single RGB565 colour (int)."""
        if w <= 0 or h <= 0:
            return
        hi = color565 >> 8
        lo = color565 & 0xFF
        row = bytes((hi, lo)) * w
        self.cs(0)
        self._window(x, y, x + w - 1, y + h - 1)
        self.dc(1)
        for _ in range(h):
            self.spi.write(row)
        self.cs(1)

    def clear(self, color565=0x0000):
        self.fill_rectangle(0, 0, self.width, self.height, color565)


def color565(r, g, b):
    """Pack 8-bit RGB into a 16-bit RGB565 int (big-endian on the wire via block/fill)."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
