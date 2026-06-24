# SSD1682 driver for Heltec Wireless Paper V1.2 (E0213A367)
# 250x122 E-Ink display, landscape orientation.
#
# Vendored from the read-only ESP/Bindicator project (D:\Projects\ESP\depg0213.py) and
# refactored to SUBCLASS framebuf.FrameBuffer (the ESP original uses composition via
# self.fb). Subclassing lets Peter Hinch's Writer render the Dot Matrix font straight into
# the driver, since Writer requires a FrameBuffer-derived device exposing .width/.height.
# The SSD1682 command sequence is unchanged from the proven original.
#
# Pin mapping: MOSI=2, CLK=3, CS=4, DC=5, RST=6, BUSY=7, Vext=45
# Buffer convention: 1 = white, 0 = black (matches e-ink + framebuf MONO_HLSB).

from machine import Pin
import time
import framebuf


class DEPG0213(framebuf.FrameBuffer):
    WIDTH = 250   # Landscape width (user-facing)
    HEIGHT = 122  # Landscape height (user-facing)

    def __init__(self, spi, cs, dc, rst, busy, vext=None):
        self.spi = spi
        self.cs = Pin(cs, Pin.OUT, value=1)
        self.dc = Pin(dc, Pin.OUT, value=0)
        self.rst = Pin(rst, Pin.OUT, value=1)
        self.busy = Pin(busy, Pin.IN, Pin.PULL_UP)

        if vext is not None:
            self.vext = Pin(vext, Pin.OUT, value=1)
            time.sleep_ms(100)
            self.vext.value(0)
            time.sleep_ms(500)

        # Landscape framebuffer — user/Writer draw into this instance directly.
        self.width = self.WIDTH    # Writer reads these
        self.height = self.HEIGHT
        self._stride = (self.WIDTH + 7) // 8  # 32 bytes/row
        self._buf = bytearray(self._stride * self.HEIGHT)
        super().__init__(self._buf, self.WIDTH, self.HEIGHT, framebuf.MONO_HLSB)

        self._hw_reset()
        self._init_display()

    # -- Low-level (Heltec-style: CS toggle per transfer) --

    def _wait(self, timeout_ms=10000):
        """SSD1682: HIGH = busy, LOW = ready."""
        start = time.ticks_ms()
        while self.busy.value() == 1:
            if time.ticks_diff(time.ticks_ms(), start) > timeout_ms:
                return False
            time.sleep_ms(10)
        time.sleep_ms(10)
        return True

    def _cmd(self, c):
        self.dc.value(0)
        self.cs.value(0)
        self.spi.write(bytes([c]))
        self.cs.value(1)
        self.dc.value(1)

    def _data(self, d):
        self.cs.value(0)
        if isinstance(d, int):
            self.spi.write(bytes([d]))
        else:
            self.spi.write(d)
        self.cs.value(1)

    def _hw_reset(self):
        self.rst.value(1); time.sleep_ms(100)
        self.rst.value(0); time.sleep_ms(100)
        self.rst.value(1); time.sleep_ms(100)

    def _init_display(self):
        self._wait()
        self._cmd(0x12)      # Soft reset
        self._wait()

        self._cmd(0x01)      # Driver output control
        self._data(0xF9)     # 250 gate lines
        self._data(0x00)

        self._cmd(0x3C)      # Border waveform
        self._data(0x01)     # White border

        self._cmd(0x18)      # Temperature sensor
        self._data(0x80)     # Internal

        self._cmd(0x37)      # Waveform register (V1.2 critical)
        self._data(0x40)
        self._data(0x80)
        self._data(0x03)
        self._data(0x0E)

        self._set_ram_area()
        self._wait()

    def _set_ram_area(self):
        self._cmd(0x11)      # Data entry: X--, Y--
        self._data(0x00)

        self._cmd(0x44)      # RAM X range: 15 -> 0
        self._data(0x0F)
        self._data(0x00)

        self._cmd(0x45)      # RAM Y range: 249 -> 0
        self._data(0xF9)
        self._data(0x00)

        self._cmd(0x4E)      # X cursor = 14
        self._data(0x0E)

        self._cmd(0x4F)      # Y cursor = 249
        self._data(0xF9)

    # -- Buffer conversion --

    def _send_buffer(self):
        """Convert landscape framebuffer to SSD1682 format and send.

        The SSD1682 has a 2-bit offset: 122 source pixels map to bit
        positions 121..0 within a 128-bit row, with a 6-bit pad at the
        end. The Heltec library handles this with (<< 6 | >> 2) shifts.

        Controller scans Y 249->0, X 14->0 then wraps to 15.
        The 16 output bytes per gate line form a 128-bit stream where
        stream position P contains source pixel (121 - P).
        """
        self._cmd(0x3C); self._data(0x01)
        self._set_ram_area()
        self._cmd(0x24)

        src = self._buf
        stride = self._stride
        row = bytearray(16)

        for gate in range(250):
            lx = 249 - gate

            for bx in range(16):
                b = 0
                for j in range(8):
                    sp = bx * 8 + j  # source pixel
                    if sp >= 122:
                        b |= 0x80 >> j  # off-panel pad -> white, else it shows as a black edge strip
                    elif src[sp * stride + (lx >> 3)] & (0x80 >> (lx & 7)):
                        b |= 0x80 >> j
                row[bx] = b

            self._data(row)

    # -- Public API --

    def update(self):
        """Full display refresh (~1.5s)."""
        self._send_buffer()
        self._cmd(0x22); self._data(0xF7)
        self._cmd(0x20)
        self._wait(timeout_ms=15000)

    def sleep(self):
        """Enter deep sleep."""
        self._cmd(0x10); self._data(0x01)
