# board_mockup.py - Render a representative board (no WiFi/server) to eyeball layout + fonts.
# Reuses the real client's render() with controlled sample data (on-time / delayed /
# cancelled / long names), so what you see is exactly what the live board will look like.
#
#   mpremote connect COM3 run board_mockup.py

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
    # London-bound only (matches the live DIRECTION_FILTER_CRS=LBG board).
    "services": [
        {"time": "14:55", "expected": "15:03", "destination": "Peterborough", "platform": "1", "is_cancelled": False},
        {"time": "15:12", "expected": "Cancelled", "destination": "Bedford", "platform": None, "is_cancelled": True},
        {"time": "15:25", "expected": "On time", "destination": "Cambridge", "platform": "3", "is_cancelled": False},
        {"time": "15:42", "expected": "On time", "destination": "London St Pancras", "platform": "1", "is_cancelled": False},
        {"time": "15:55", "expected": "16:01", "destination": "Bedford", "platform": "2", "is_cancelled": False},
    ],
}

rc.render(d, wh, wr, wf, SAMPLE)
d.update()
print("mockup rendered")
