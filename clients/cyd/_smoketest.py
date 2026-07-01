# Bounded bring-up test for the RailInfo CYD client.
#   mpremote connect COM4 run _smoketest.py
# Reuses the client's own functions (importing it does NOT start the main loop, thanks to the
# __main__ guard): init the TFT, connect WiFi, fetch one board, render it. Not a production
# file - just a quick on-device check of the display + driver + font pipeline end to end.

import time
import railinfo_client as rc

display, cfg = rc.init_display()
print("display init ok:", display.width, "x", display.height)

board = rc.Board(display)
wlan = rc.connect_wifi(board)
print("wifi connected:", bool(wlan) and wlan.isconnected())
if wlan:
    print("ip:", wlan.ifconfig()[0])

data = rc.http_get_json(rc.SERVER_URL + "?view=departures")
print("status:", data.get("status"), "station:", data.get("station"),
      "services:", len(data.get("services") or []))

if data.get("status") == "starting":
    board.show_status(["RailInfo", "Starting up..."])
    time.sleep(6)  # give the lazy server a moment to make its first LDBWS fetch
    data = rc.http_get_json(rc.SERVER_URL + "?view=departures")
    print("after wait -> status:", data.get("status"),
          "services:", len(data.get("services") or []))

board.render_departures(data, True)
print("rendered departures. In the full client, BOOT (GPIO0) or a screen tap cycles views.")
print("smoketest done")
