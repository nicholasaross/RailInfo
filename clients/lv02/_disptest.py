# On-panel driver + orientation test (no WiFi). Corner colour blocks + a text strip, so we can
# confirm the parallel driver works and the rotation/offsets are right.
import framebuf
from boards import init_display
from st7789 import color565
from writer import Writer
import dotmatrix19


class _Strip(framebuf.FrameBuffer):
    def __init__(self, w, h):
        self.width = w
        self.height = h
        self.buf = bytearray(((w + 7) // 8) * h)
        super().__init__(self.buf, w, h, framebuf.MONO_HLSB)


d, cfg = init_display()
W, H = d.width, d.height
print("display", W, "x", H)

d.clear(color565(0, 0, 0))
s = 30
d.fill_rectangle(0, 0, s, s, color565(255, 0, 0))              # top-left  RED
d.fill_rectangle(W - s, 0, s, s, color565(0, 255, 0))          # top-right GREEN
d.fill_rectangle(0, H - s, s, s, color565(0, 0, 255))          # bot-left  BLUE
d.fill_rectangle(W - s, H - s, s, s, color565(255, 255, 255))  # bot-right WHITE

msg = "LV02 OK"
sw = 8 * len(msg) + 4
strip = _Strip(sw, 22)
w = Writer(strip, dotmatrix19, verbose=False)
Writer.set_textpos(strip, 0, 0)
w.printstring(msg)

buf = bytearray(sw * 22 * 2)
amber = color565(255, 150, 0)
hi = amber >> 8
lo = amber & 0xFF
for yy in range(22):
    for xx in range(sw):
        if strip.pixel(xx, yy):
            o = (yy * sw + xx) * 2
            buf[o] = hi
            buf[o + 1] = lo
d.block(40, 40, 40 + sw - 1, 40 + 22 - 1, buf)
print("done: TL=red TR=green BL=blue BR=white, amber 'LV02 OK' near top-left")
