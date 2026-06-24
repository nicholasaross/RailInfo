# multi_size_demo.py - Compare clean Dot Matrix sizes on the Heltec to pick board sizes.
#
# One size per screen (proportional, tabular + centered digits). Each screen: a crisp
# built-in-font label, then a realistic departure row and a 0-9 ruler in that font, so you
# can judge legibility and digit alignment. Only "even-stroke" sizes are shown (the ones
# whose dot grid renders cleanly). Auto-advances quickly and loops.
#
# Watch and give yes/no per label (e.g. "19 yes, 16 no").
#
#   mpremote connect COM3 run multi_size_demo.py

import gc
import sys
import time
from boards import init_display
from writer import Writer

SIZES = [20, 21, 22, 23, 24, 28, 29, 30]
ROW = "11:04 Redhill P1"
RULER = "0123456789"
DWELL_S = 4


def run():
    d, b = init_display()
    while True:
        for sz in SIZES:
            name = "dotmatrix%d" % sz
            try:
                mod = __import__(name)
            except Exception as e:  # noqa: BLE001
                print("skip", name, e)
                continue
            d.fill(1)
            d.text("%dpx" % sz, 2, 2, 0)        # crisp built-in 8x8 label
            d.hline(0, 12, d.width, 0)
            w = Writer(d, mod, verbose=False)
            w.set_clip(True, True, False)
            y = 15
            for line in (ROW, RULER):
                if y + mod.height() > d.height:
                    break
                Writer.set_textpos(d, y, 0)
                w.printstring(line, True)       # black on white
                y += mod.height() + 1
            d.update()
            print("shown:", sz)
            if name in sys.modules:
                del sys.modules[name]
            del mod, w
            gc.collect()
            time.sleep(DWELL_S)


run()
