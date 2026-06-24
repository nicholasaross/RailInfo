# dump_board.py - render the mock board and print it as ASCII over serial, so layout issues
# (e.g. a stray bar) can be diagnosed without seeing the panel.  mpremote connect COM3 run dump_board.py

import railinfo_client as rc

d, b = rc.init_display()
wh = rc._make_writer(d, rc.HEADER_FONT)
wr = rc._make_writer(d, rc.ROW_FONT)
wf = rc._make_writer(d, rc.FOOTER_FONT)

SAMPLE = {
    "station": "Earlswood (Surrey)",
    "crs": "ELD",
    "generated_at": "2026-06-23T14:52:00",
    "stops_index": 0,
    "calling_at": ["Redhill", "Merstham", "East Croydon", "London Bridge"],
    "services": [
        {"time": "14:55", "expected": "15:03", "destination": "Peterborough", "platform": "1", "is_cancelled": False},
        {"time": "15:12", "expected": "Cancelled", "destination": "Bedford", "platform": None, "is_cancelled": True},
        {"time": "15:25", "expected": "On time", "destination": "Cambridge", "platform": "3", "is_cancelled": False},
        {"time": "15:42", "expected": "On time", "destination": "London St Pancras", "platform": "1", "is_cancelled": False},
        {"time": "15:55", "expected": "16:01", "destination": "Bedford", "platform": "2", "is_cancelled": False},
    ],
}

rc.render(d, wh, wr, wf, SAMPLE)  # framebuffer only (no e-ink refresh)

buf = d._buf
stride = d._stride


def ink(x, y):
    return (buf[y * stride + (x >> 3)] & (0x80 >> (x & 7))) == 0  # bit 0 = black


# Downsample to 50 cols x 61 rows (5px x 2px cells); '#'=mostly ink, '+'=some, ' '=none.
for y in range(0, d.height, 2):
    line = []
    for c in range(0, d.width, 5):
        n = sum(ink(x, yy) for x in range(c, min(c + 5, d.width)) for yy in (y, min(y + 1, d.height - 1)))
        line.append("#" if n >= 4 else ("+" if n else " "))
    print("".join(line))
print("END")
