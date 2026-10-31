# Bounded bring-up test for the RailInfo CYD Portrait client.
#   mpremote connect COM7 run _smoketest.py
# Reuses the client's own functions (importing it does NOT start the main loop, thanks to the
# __main__ guard): init the TFT, connect WiFi, fetch the split board once, render it. Not a
# production file - just a quick on-device check of the display + driver + font pipeline end to end.

import time
import railinfo_client as rc

display, cfg = rc.init_display()
print("display init ok:", display.width, "x", display.height)

board = rc.Board(display)
print("layout: sections at y =", board.SECTION_Y, "| rows per half:", board.ROWS)
wlan = rc.connect_wifi(board)
print("wifi connected:", bool(wlan) and wlan.isconnected())
if wlan:
    print("ip:", wlan.ipconfig("addr4")[0] if hasattr(wlan, "ipconfig") else wlan.ifconfig()[0])

url = rc.SERVER_URL + "?view=split"
data = rc.http_get_json(url)
if data.get("status") == "starting":
    board.show_status(["RailInfo", "Starting up..."])
    time.sleep(6)  # give the lazy server a moment to make its first LDBWS fetch
    data = rc.http_get_json(url)
print("status:", data.get("status"), "station:", data.get("station"),
      "north:", len(data.get("northbound") or []), "south:", len(data.get("southbound") or []))

board.render_split(data, True)
print("rendered split board")
print("smoketest done")
