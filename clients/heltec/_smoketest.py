# Bounded bring-up test for the RailInfo Heltec client.
#   mpremote connect COM3 run _smoketest.py
# Reuses the client's own functions (importing it does NOT start the main loop, thanks to the
# __main__ guard), does WiFi + two fetch/render cycles, and reports change-detection. Not a
# production file - just a quick on-device check.

import time
import railinfo_client as rc

d, board = rc.init_display()
w16 = rc._make_writer(d, rc.dotmatrix16)
w10 = rc._make_writer(d, rc.dotmatrix10)

wlan = rc.connect_wifi(d, w16)
print("wifi connected:", bool(wlan) and wlan.isconnected())
if wlan:
    print("ip:", wlan.ifconfig()[0], "rssi:", wlan.status("rssi"))

data = rc.http_get_json(rc.SERVER_URL)
print("station:", data.get("station"), "services:", len(data.get("services") or []))
rc.render(d, w16, w10, data)
d.update()
last = bytes(d._buf)
print("cycle 1: rendered + refreshed")

time.sleep(6)
data = rc.http_get_json(rc.SERVER_URL)
rc.render(d, w16, w10, data)
cur = bytes(d._buf)
print("cycle 2: frame changed =", cur != last)
if cur != last:
    d.update()
print("smoketest done")
