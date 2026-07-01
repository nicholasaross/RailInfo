# ili9341.py - minimal ILI9341/ILI9342 SPI driver for the CYD (ESP32-2432S028), MicroPython.
#
# Purpose-built for the RailInfo CYD client: it does the init handshake and exposes exactly
# what the renderer needs - block() to push a pre-built RGB565 pixel buffer to a rectangle,
# plus fill_rectangle()/clear() for black backgrounds. It deliberately has NO on-device font
# or shape drawing: text is rendered elsewhere (Peter Hinch's Writer into a 1-bpp framebuf,
# then colourised to RGB565 by the client) and pushed here via block(). That keeps this file
# small and keeps the whole project on the single Dot Matrix typeface.
#
# PANEL VARIANT: the ESP32-2432S028 ships with one of THREE controllers (ILI9341, ILI9342,
# ST7789V). This unit (marked "H685") is an **ILI9342** — which is natively 320x240 LANDSCAPE
# (unlike the ILI9341's native 240x320 portrait). So the landscape ROTATION must NOT set the
# MADCTL transpose bit (MV); setting MV rotates the ILI9342 to 240x320 and everything renders
# half-width. The ILI9341 init sequence below drives the ILI9342 fine (they're near-identical);
# only the ROTATION differs. This unit is also an RGB panel (BGR bit left clear; setting it
# swapped red/blue at bring-up).
#
# Init sequence is the well-known Adafruit/rdagger ILI9341 sequence (16-bit colour, 0x3A=0x55).

from time import sleep_ms
from micropython import const

# Commands
_SWRESET = const(0x01)
_SLPOUT = const(0x11)
_DISPON = const(0x29)
_CASET = const(0x2A)
_PASET = const(0x2B)
_RAMWR = const(0x2C)
_MADCTL = const(0x36)
_PIXFMT = const(0x3A)

# MADCTL bits (for building a ROTATION byte in boards.py)
MADCTL_MY = const(0x80)
MADCTL_MX = const(0x40)
MADCTL_MV = const(0x20)
MADCTL_BGR = const(0x08)

# ILI9342 native landscape, un-mirrored, RGB: MX only (0x40) — NO MV (this panel is already
# landscape; MV would rotate it to half-width) and NO BGR. Verified on the H685 unit: 0x40 gives
# a forward-facing image, red in the physical top-left. Add MADCTL_BGR (0x08) if red/blue swap;
# toggle MX/MY to un-mirror/flip a differently-oriented panel. (An ILI9341 CYD variant WOULD
# need MV set here for landscape — that's the key per-variant difference.)
ROTATION_LANDSCAPE = const(MADCTL_MX)  # 0x40


class ILI9341:
    def __init__(self, spi, *, cs, dc, rst, width=320, height=240,
                 rotation=ROTATION_LANDSCAPE):
        self.spi = spi
        self.cs = cs
        self.dc = dc
        self.rst = rst
        self.width = width
        self.height = height
        self._rotation = rotation
        for p in (cs, dc):
            p.init(p.OUT, value=1)
        if rst is not None:
            rst.init(rst.OUT, value=1)
        self._reset()
        self._init_display()
        self.clear()

    # --- low-level SPI ---
    # CS is framed once per logical transaction (command + its data), NOT per byte: the ILI9341
    # treats CS going high as the end of the write, so pixel data after RAMWR must share one
    # CS-low span with the command. DC selects command (0) vs data (1) for each chunk.

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
        if self.rst is None:
            self._write_cmd(_SWRESET)
            sleep_ms(150)
            return
        self.rst(1); sleep_ms(50)
        self.rst(0); sleep_ms(50)
        self.rst(1); sleep_ms(150)

    def _init_display(self):
        self._write_cmd(0xEF, 0x03, 0x80, 0x02)
        self._write_cmd(0xCF, 0x00, 0xC1, 0x30)
        self._write_cmd(0xED, 0x64, 0x03, 0x12, 0x81)
        self._write_cmd(0xE8, 0x85, 0x00, 0x78)
        self._write_cmd(0xCB, 0x39, 0x2C, 0x00, 0x34, 0x02)
        self._write_cmd(0xF7, 0x20)
        self._write_cmd(0xEA, 0x00, 0x00)
        self._write_cmd(0xC0, 0x23)               # power control 1
        self._write_cmd(0xC1, 0x10)               # power control 2
        self._write_cmd(0xC5, 0x3E, 0x28)         # VCOM control 1
        self._write_cmd(0xC7, 0x86)               # VCOM control 2
        self._write_cmd(_MADCTL, self._rotation)
        self._write_cmd(0x37, 0x00)               # vertical scroll start
        self._write_cmd(_PIXFMT, 0x55)            # 16-bit/pixel
        self._write_cmd(0xB1, 0x00, 0x18)         # frame rate
        self._write_cmd(0xB6, 0x08, 0x82, 0x27)   # display function control
        self._write_cmd(0xF2, 0x00)               # 3-gamma off
        self._write_cmd(0x26, 0x01)               # gamma curve
        self._write_cmd(0xE0, 0x0F, 0x31, 0x2B, 0x0C, 0x0E, 0x08, 0x4E, 0xF1,
                        0x37, 0x07, 0x10, 0x03, 0x0E, 0x09, 0x00)
        self._write_cmd(0xE1, 0x00, 0x0E, 0x14, 0x03, 0x11, 0x07, 0x31, 0xC1,
                        0x48, 0x08, 0x0F, 0x0C, 0x31, 0x36, 0x0F)
        self._write_cmd(_SLPOUT)
        sleep_ms(120)
        self._write_cmd(_DISPON)
        sleep_ms(20)

    # --- windowing / blits ---

    def _window(self, x0, y0, x1, y1):
        """Set the address window and issue RAMWR. Caller holds CS low and follows with data."""
        self._cmd(_CASET)
        self._data(bytes((x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)))
        self._cmd(_PASET)
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
