# demo.py - Static Dot Matrix capability demo for Heltec Wireless Paper V1.2.
#
# Proves the bring-up end of Phase 4: the refactored e-ink driver + Peter Hinch's Writer +
# the RailInfo Dot Matrix font, all rendering on-device. Two static screens:
#   Phase A - fills EVERY character cell with a column ruler, so the full X/Y character
#             grid (the device's capability) is visible at a glance.
#   Phase B - draws the capacity (cols x rows) for each available font size.
# Both are also printed over serial.
#
# Run (lib modules must already be on the device under /lib):
#   mpremote connect COM3 run demo.py

from machine import Pin, SPI
import time
from depg0213 import DEPG0213
from writer import Writer
import dotmatrix10
import dotmatrix16
import dotmatrix20

FONTS = (("10", dotmatrix10), ("16", dotmatrix16), ("20", dotmatrix20))


def init_display():
    spi = SPI(1, baudrate=6_000_000, polarity=0, phase=0, sck=Pin(3), mosi=Pin(2))
    return DEPG0213(spi, cs=4, dc=5, rst=6, busy=7, vext=45)


def grid_dims(font, w, h):
    """How many whole monospaced cells fit: (columns, rows)."""
    return w // font.max_width(), h // font.height()


def _writer(d, font):
    wri = Writer(d, font, verbose=False)
    wri.set_clip(True, True, False)  # row_clip, col_clip, wrap=False
    return wri


def fill_grid(d, font):
    """Populate every cell with a column ruler (cell shows column index % 10).

    invert=True renders black glyphs on white, the right way round for e-ink.
    """
    wri = _writer(d, font)
    cols, rows = grid_dims(font, d.width, d.height)
    ruler = "".join(str(c % 10) for c in range(cols))
    for r in range(rows):
        Writer.set_textpos(d, r * font.height(), 0)
        wri.printstring(ruler, True)
    return cols, rows


def summary(d):
    d.fill(1)
    head = _writer(d, dotmatrix16)
    Writer.set_textpos(d, 0, 0)
    head.printstring("Dot Matrix - max chars", True)
    body = _writer(d, dotmatrix10)
    y = dotmatrix16.height() + 3
    for name, f in FONTS:
        cols, rows = grid_dims(f, d.width, d.height)
        Writer.set_textpos(d, y, 0)
        body.printstring(
            "{}px cell {}x{}  ->  {} x {} = {}".format(
                name, f.max_width(), f.height(), cols, rows, cols * rows
            ),
            True,
        )
        y += dotmatrix10.height() + 2


def main():
    d = init_display()

    # Phase A: capability grid -- every cell populated with the densest font.
    d.fill(1)
    cols, rows = fill_grid(d, dotmatrix10)
    d.update()
    print("=== Dot Matrix display capability (Heltec 250x122) ===")
    for name, f in FONTS:
        c, r = grid_dims(f, d.width, d.height)
        print("dotmatrix{:>2}: cell {}x{}px -> {} cols x {} rows = {} chars".format(
            name, f.max_width(), f.height(), c, r, c * r))
    print("Phase A grid shown: {} x {} = {} cells".format(cols, rows, cols * rows))

    time.sleep(5)

    # Phase B: on-screen capacity summary.
    summary(d)
    d.update()
    print("Phase B summary shown. Demo done.")


main()
