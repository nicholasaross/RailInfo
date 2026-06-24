# portrait_mockup.py - render a portrait all-departures list to the panel (rotated) and dump
# the portrait surface as ASCII to verify content.  mpremote connect COM3 run portrait_mockup.py

import railinfo_client as rc

d, b = rc.init_display()
port = rc.PortraitCanvas()
wri = rc._make_writer(port, rc.HEADER_FONT)

SAMPLE = {
    "generated_at": "2026-06-23T20:14:00",
    "services": [
        {"time": "20:09", "expected": "20:17", "destination": "Horsham", "platform": "2", "is_cancelled": False},
        {"time": "20:12", "expected": "Cancelled", "destination": "Luton", "platform": None, "is_cancelled": True},
        {"time": "20:25", "expected": "On time", "destination": "Peterborough", "platform": "1", "is_cancelled": False},
        {"time": "20:28", "expected": "On time", "destination": "Gatwick Airport", "platform": "2", "is_cancelled": False},
        {"time": "20:42", "expected": "Cancelled", "destination": "Bedford", "platform": None, "is_cancelled": True},
        {"time": "20:55", "expected": "21:02", "destination": "Brighton", "platform": "2", "is_cancelled": False},
        {"time": "20:56", "expected": "On time", "destination": "Peterborough", "platform": "1", "is_cancelled": False},
        {"time": "21:09", "expected": "On time", "destination": "Three Bridges", "platform": "2", "is_cancelled": False},
        {"time": "21:12", "expected": "On time", "destination": "Luton", "platform": "4", "is_cancelled": False},
        {"time": "21:25", "expected": "On time", "destination": "Cambridge", "platform": "1", "is_cancelled": False},
    ],
}

rc.render_portrait(d, port, wri, SAMPLE, "All departures")
d.update()
print("portrait rendered")

# Dump the portrait surface (readable, downsampled) to verify the list content.
buf, st = port._buf, port._stride


def ink(x, y):
    return (buf[y * st + (x >> 3)] & (0x80 >> (x & 7))) == 0


for y in range(0, port.height, 4):
    print("".join(
        "#" if any(ink(x, yy) for x in range(c, min(c + 3, port.width)) for yy in (y, min(y + 3, port.height - 1)))
        else " "
        for c in range(0, port.width, 3)
    ))
print("END")
