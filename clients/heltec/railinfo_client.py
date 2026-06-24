# railinfo_client.py - RailInfo e-ink client for Heltec Wireless Paper V1.2 (MicroPython).
#
# Connects to WiFi (with retries + on-screen progress), polls the RailInfo --serve JSON API
# (/board) every few seconds, and renders a live National Rail departure board in the
# Dot Matrix font. E-ink is slow, so the panel only does its ~1.5s full refresh when the
# rendered frame actually CHANGES (a framebuffer byte-compare) - the board ticks roughly
# once a minute, so polling every 5s stays responsive without ghosting/wearing the panel.
#
# Fonts are MONOSPACED Dot Matrix at clean sizes with centered tabular digits:
#   - departure rows: 19px  (~20 columns, ~5 rows)
#   - header + footer: 9px  (~50 columns)
# Based on the read-only ESP/Bindicator project (WiFi connect/retry, depg0213 driver).
#
# Deploy: lib modules under /lib, plus boards.py + config.py + this file (as main.py to
# autostart). See README.md.

import network
import time
import json

try:
    import usocket as socket
except ImportError:
    import socket

from config import WIFI_SSID, WIFI_PASSWORD, SERVER_URL
try:
    from config import POLL_INTERVAL_S
except ImportError:
    POLL_INTERVAL_S = 5

import framebuf
from machine import Pin

from boards import init_display
from writer import Writer
import dotmatrix9
import dotmatrix19

# --- Fonts by role ---
HEADER_FONT = dotmatrix9
ROW_FONT = dotmatrix19
FOOTER_FONT = dotmatrix9

# --- Timing / behaviour ---
WIFI_MAX_ATTEMPTS = 5
WIFI_POLL_COUNT = 20
WIFI_POLL_INTERVAL_MS = 500
WIFI_RETRY_DELAY_S = 5
WIFI_FAIL_SLEEP_S = 10
FETCH_FAIL_LIMIT = 3
HTTP_TIMEOUT_S = 8
MAX_ROWS = 5

# --- Layout (pixels) ---
HEADER_Y = 1
SEP_Y = 11       # separator under the header (station/time) line
ROW_Y0 = 14
ROW_PITCH = 19

_ABBR = (
    ("London ", "Ldn "),
    (" International", " Intl"),
    (" Airport", " Apt"),
    (" Parkway", " Pkwy"),
    (" Junction", " Jn"),
    (" Central", " Ctl"),
    (" Street", " St"),
)


# --- Text helpers (MicroPython lacks str.ljust/rjust) ---

def _abbrev(s):
    for a, b in _ABBR:
        s = s.replace(a, b)
    return s


def _fit_px(wri, s, max_px):
    """Truncate (after abbreviating) so the string fits max_px pixels in wri's font."""
    s = _abbrev(s or "")
    while len(s) > 1 and wri.stringlen(s) > max_px:
        s = s[:-1]
    return s


# --- Rendering ---

def _make_writer(display, font):
    wri = Writer(display, font, verbose=False)
    wri.set_clip(True, True, False)  # row_clip, col_clip, wrap=False
    return wri


def _draw(wri, x, y, s):
    Writer.set_textpos(wri.device, y, x)
    wri.printstring(s, True)  # black on white


def _disp_time(svc):
    """Scheduled time, plus ' :MM' of the revised minute if delayed (e.g. '15:15 :18')."""
    sched = svc.get("time") or "--:--"
    exp = svc.get("expected") or ""
    if ":" in exp and exp != sched:
        return sched + " :" + exp.split(":")[1]
    return sched


def _header(display, wri, data):
    """Draw station (left) + clock (right), pixel-aligned for the proportional font."""
    gen = data.get("generated_at") or ""
    clock = gen.split("T")[1][:5] if "T" in gen else ""
    clock_w = wri.stringlen(clock) if clock else 0
    station = _fit_px(wri, data.get("station") or data.get("crs") or "RailInfo",
                      display.width - clock_w - 4)
    _draw(wri, 0, HEADER_Y, station)
    if clock:
        _draw(wri, display.width - clock_w, HEADER_Y, clock)


def _draw_row(wri, display, y, svc):
    # Station (destination/origin) left; platform + time right-justified (order: Station,
    # Platform, Time). A cancelled service shows just 'cancelled', fully right-justified.
    if svc.get("is_cancelled"):
        right = "cancelled"
    else:
        p = svc.get("platform")
        right = (("P" + p + " ") if p else "") + _disp_time(svc)
    right_w = wri.stringlen(right)
    dest = _fit_px(wri, svc.get("destination") or svc.get("destination_crs") or "?",
                   display.width - right_w - 4)
    _draw(wri, 0, y, dest)
    _draw(wri, display.width - right_w, y, right)


def _footer(wri, display, data):
    ca = data.get("calling_at") or []
    if not ca:
        return None
    return _fit_px(wri, "Calling: " + ", ".join(ca), display.width)


def render(display, wri_h, wri_r, wri_f, data):
    """Draw the board into the framebuffer (no e-ink refresh here)."""
    display.fill(1)  # white
    _header(display, wri_h, data)
    display.hline(0, SEP_Y, display.width, 0)

    services = data.get("services") or []
    if not services:
        _draw(wri_r, 0, ROW_Y0, "No departures")
    else:
        y = ROW_Y0
        for svc in services[:MAX_ROWS]:
            _draw_row(wri_r, display, y, svc)
            y += ROW_PITCH

    foot = _footer(wri_f, display, data)
    if foot:
        fy = display.height - FOOTER_FONT.height()
        display.hline(0, fy - 2, display.width, 0)
        _draw(wri_f, 0, fy, foot)


def _screen(display, wri, lines):
    """Full-refresh a short status/error message (transient, not the data board)."""
    display.fill(1)
    y = 4
    for ln in lines:
        _draw(wri, 2, y, ln)
        y += wri.font.height() + 3
    display.update()


# --- Networking ---

def connect_wifi(display, wri):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    for attempt in range(1, WIFI_MAX_ATTEMPTS + 1):
        if wlan.isconnected():
            return wlan
        _screen(display, wri, ["RailInfo", "WiFi {}/{}".format(attempt, WIFI_MAX_ATTEMPTS)])
        try:
            wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        except Exception:
            pass
        for _ in range(WIFI_POLL_COUNT):
            if wlan.isconnected():
                return wlan
            time.sleep_ms(WIFI_POLL_INTERVAL_MS)
        try:
            wlan.disconnect()
        except Exception:
            pass
        if attempt < WIFI_MAX_ATTEMPTS:
            time.sleep(WIFI_RETRY_DELAY_S)
    return None


def http_get_json(url):
    """Minimal dependency-free HTTP/1.0 GET returning parsed JSON."""
    proto, _, rest = url.partition("://")
    hostport, _, path = rest.partition("/")
    path = "/" + path
    host, _, port = hostport.partition(":")
    port = int(port) if port else 80

    addr = socket.getaddrinfo(host, port)[0][-1]
    s = socket.socket()
    s.settimeout(HTTP_TIMEOUT_S)
    try:
        s.connect(addr)
        s.send(("GET " + path + " HTTP/1.0\r\nHost: " + host +
                "\r\nConnection: close\r\n\r\n").encode())
        buf = b""
        while True:
            chunk = s.recv(512)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()

    head, _, body = buf.partition(b"\r\n\r\n")
    status = int(head.split(b" ")[1])
    if status != 200:
        raise OSError("HTTP " + str(status))
    return json.loads(body)


# --- Portrait views (all departures / arrivals), rendered rotated 90 degrees ---

class PortraitCanvas(framebuf.FrameBuffer):
    """A 121x250 drawing surface (the panel on its side) for Writer to render into.

    Width is 121 (not the full 122) to leave a 1px margin on the panel's far edge, which the
    e-ink doesn't render.
    """

    WIDTH = 121
    HEIGHT = 250

    def __init__(self):
        self.width = self.WIDTH
        self.height = self.HEIGHT
        self._stride = (self.WIDTH + 7) // 8  # 16 bytes/row
        self._buf = bytearray(self._stride * self.HEIGHT)
        super().__init__(self._buf, self.WIDTH, self.HEIGHT, framebuf.MONO_HLSB)


def _blit_portrait(panel, port):
    """Rotate the portrait surface 90 degrees clockwise onto the landscape panel buffer.

    panel(249-py, px) <- port(px, py). The panel is filled white first, so the 1px column the
    portrait surface omits (px == 121) stays white instead of retaining stale pixels.
    """
    panel.fill(1)  # white; the transpose then paints only the (sparse) black pixels
    pbuf, lbuf = port._buf, panel._buf
    pst, lst = port._stride, panel._stride
    w = port.width
    for py in range(250):
        prow = py * pst
        lcb = (249 - py) >> 3
        nlbit = (~(0x80 >> ((249 - py) & 7))) & 0xFF
        for px in range(w):
            if not (pbuf[prow + (px >> 3)] & (0x80 >> (px & 7))):  # black in portrait
                lbuf[px * lst + lcb] &= nlbit  # paint black on the panel


def render_portrait(panel, port, wri, data, title):
    """Draw a tall list (title + clock, then services) and rotate it onto the panel."""
    port.fill(1)
    gen = data.get("generated_at") or ""
    clock = gen.split("T")[1][:5] if "T" in gen else ""
    cw = wri.stringlen(clock) if clock else 0
    _draw(wri, 0, 0, _fit_px(wri, title, port.width - cw - 4))
    if clock:
        _draw(wri, port.width - cw, 0, clock)
    port.hline(0, 10, port.width, 0)
    y = 13
    for svc in (data.get("services") or []):
        if y + wri.font.height() > port.height:
            break
        _draw_row(wri, port, y, svc)
        y += 10
    _blit_portrait(panel, port)


# --- View modes, cycled by the PRG button: (view query, is_portrait, title) ---
MODES = (
    ("departures", False, ""),
    ("all", True, "All departures"),
    ("arrivals", True, "Arrivals"),
)
PRG_PIN = 0  # Heltec PRG / USER button (GPIO0)

# PRG is handled by a pin IRQ rather than polling, so a press is latched even while we're blocked
# in a socket fetch or a ~1.5s e-ink refresh - those windows are most of each cycle, and a press
# that lands there used to be lost (the board only seemed to react when the data happened to
# change). The IRQ just sets a flag (time-based debounce); the main loop consumes it at a safe
# point and advances the view regardless of whether the board data updated.
_prg_flag = False
_prg_last_ms = 0
PRG_DEBOUNCE_MS = 300


def _prg_irq(pin):
    global _prg_flag, _prg_last_ms
    t = time.ticks_ms()
    if time.ticks_diff(t, _prg_last_ms) > PRG_DEBOUNCE_MS:
        _prg_last_ms = t
        _prg_flag = True


def _setup_button():
    global _prg_flag
    btn = Pin(PRG_PIN, Pin.IN, Pin.PULL_UP)
    btn.irq(trigger=Pin.IRQ_FALLING, handler=_prg_irq)
    _prg_flag = False  # ignore any edge from enabling the pull-up
    return btn  # keep a reference alive so the IRQ stays registered


def _take_press():
    """True (and clear the latch) if PRG has been pressed since we last checked."""
    global _prg_flag
    if _prg_flag:
        _prg_flag = False
        return True
    return False


def _wait(secs):
    """Sleep up to `secs`, returning early the moment a PRG press is latched."""
    end = time.ticks_add(time.ticks_ms(), int(secs * 1000))
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        if _prg_flag:
            return
        time.sleep_ms(20)


# --- Main loop ---

def run():
    display, board = init_display()
    wri_h = _make_writer(display, HEADER_FONT)
    wri_r = _make_writer(display, ROW_FONT)
    wri_f = _make_writer(display, FOOTER_FONT)
    port = PortraitCanvas()
    wri_p = _make_writer(port, HEADER_FONT)  # 9px into the portrait surface
    btn = _setup_button()  # kept referenced so the PRG IRQ stays live
    mode = 0

    while True:
        wlan = connect_wifi(display, wri_r)
        if not wlan:
            _screen(display, wri_r, ["RailInfo", "WiFi failed", "Retrying..."])
            time.sleep(WIFI_FAIL_SLEEP_S)
            continue

        last = None
        force = True  # force a refresh on entry and after a mode change
        fails = 0
        while True:
            if _take_press():  # PRG pressed (possibly mid-fetch/refresh) -> next view now
                mode = (mode + 1) % len(MODES)
                force = True
                last = None
                print("mode ->", MODES[mode][0])

            view, portrait, title = MODES[mode]
            try:
                data = http_get_json(SERVER_URL + "?view=" + view)
                fails = 0
            except Exception as exc:
                fails += 1
                print("fetch failed:", exc)
                if not wlan.isconnected():
                    break
                if fails >= FETCH_FAIL_LIMIT:
                    _screen(display, wri_r, ["RailInfo", "Server error"])
                    last = None
                _wait(POLL_INTERVAL_S)
                continue

            if portrait:
                render_portrait(display, port, wri_p, data, title)
            else:
                render(display, wri_h, wri_r, wri_f, data)

            cur = bytes(display._buf)
            if force or cur != last:
                display.update()
                last = cur
                force = False
                print("refreshed:", view)
            else:
                print("unchanged:", view)

            _wait(POLL_INTERVAL_S)  # returns early on a PRG press; handled at loop top
            if not wlan.isconnected():
                break


if __name__ == "__main__":
    run()
