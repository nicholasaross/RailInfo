# Bring-up display test for the NM-TV-154 - draws known shapes so a human can verify the
# panel config (orientation / colour order / inversion / offsets) before running the client.
#   mpremote connect COM5 run _displaytest.py
#
# Expected on a correctly configured panel:
#   - top half: three vertical bars reading RED, GREEN, BLUE left to right
#   - a WHITE square in the top-left corner
#   - an AMBER bar across the very bottom edge (flush, no gap / no clipping)
#   - the rest black

from boards import init_display
from st7789 import color565

d, cfg = init_display()
print("display init ok:", d.width, "x", d.height)

d.clear()
d.fill_rectangle(0, 0, 80, 120, color565(255, 0, 0))      # red
d.fill_rectangle(80, 0, 80, 120, color565(0, 255, 0))     # green
d.fill_rectangle(160, 0, 80, 120, color565(0, 0, 255))    # blue
d.fill_rectangle(0, 0, 24, 24, color565(255, 255, 255))   # white corner marker (top-left)
d.fill_rectangle(0, 228, 240, 12, color565(255, 150, 0))  # amber bottom edge bar
print("drawn: RGB bars top, white top-left, amber bottom bar")
