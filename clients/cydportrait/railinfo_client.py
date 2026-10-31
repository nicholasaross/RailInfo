# railinfo_client.py - RailInfo CYD Portrait client (ESP32-2432S028 in a portrait stand), MicroPython.
#
# A single-screen variant of the CYD client, for a CYD mounted PORTRAIT (240x320, USB/power at the
# bottom) in a 3D-printed stand with no openings for the buttons - so there is no view cycling and
# no input at all. One fixed screen shows every departure, split by direction:
#   * top half    - northbound trains (the server's direction filter: RDH from Earlswood)
#   * bottom half - southbound trains (the same filter CRS, opposite direction)
# It polls the RailInfo --serve JSON API's `split` view (/board?view=split), which returns the two
# lists ready-made, and renders them in the CYD client's colour dot-matrix look: whole rows in amber
# (on time), orange (delayed, "HH:MM :MM") or red (cancelled).
#
# Rendering is the CYD client's strip-blit approach (no PSRAM, so no full RGB565 framebuffer): each
# region (header, section titles, each row) is drawn with Peter Hinch's Writer into a small 1-bpp
# `Strip`, then colourised to RGB565 and pushed via the driver's block(). Per-region change
# detection means only rows whose pixels actually changed get re-blitted, so a static board doesn't
# flicker.
#
# Deploy: lib modules under /lib, plus boards.py + config.py + this file (as main.py to
# autostart). See README.md.

import gc
import sys
import network
import time
import json

try:
    import usocket as socket
except ImportError:
    import socket

import framebuf

from config import WIFI_SSID, WIFI_PASSWORD, SERVER_URL
try:
    from config import POLL_INTERVAL_S
except ImportError:
    POLL_INTERVAL_S = 5

from boards import init_display
from ili9341 import color565
from writer import Writer
import dotmatrix19

# --- Font ---
# One clean size, dotmatrix19 at 1x (on this sharp TFT the dot-matrix TTF only rasterises crisply at
# small sizes). The 240px portrait width still fits a full row: the widest right block, a delayed
# "P1 14:55 :58", is 96px, leaving ~140px for the destination ("Peterborough" is 120px).
FONT = dotmatrix19

# Section titles: top half / bottom half.
NORTH_TITLE = "Northbound"
SOUTH_TITLE = "Southbound"
ARROW_ROWS = 7  # section-title triangle: 7 rows tall, 13 dots wide at the base

# --- Colours (RGB565) - the CYD client's palette, tuned on its green-heavy TFT ---
# Amber on time, deep orange delayed, red cancelled (green levels 150 / 60 / 0 keep the three
# states distinct as thin text). Section titles are light grey so they read as labels, not trains.
BG = 0x0000
AMBER = color565(255, 150, 0)
ORANGE = color565(255, 60, 0)
RED = color565(255, 0, 0)
HEADER_C = AMBER
TITLE_C = color565(200, 200, 200)
SEP_C = color565(90, 90, 90)

# --- Timing / behaviour (mirrors the CYD client) ---
WIFI_MAX_ATTEMPTS = 5
WIFI_POLL_COUNT = 20
WIFI_POLL_INTERVAL_MS = 500
WIFI_RETRY_DELAY_S = 5
WIFI_FAIL_SLEEP_S = 10
FETCH_FAIL_LIMIT = 3
HTTP_TIMEOUT_S = 8

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


def _disp_time(svc):
    """Scheduled time, plus ' :MM' of the revised minute if delayed (e.g. '15:15 :18')."""
    sched = svc.get("time") or "--:--"
    exp = svc.get("expected") or ""
    if ":" in exp and exp != sched:
        return sched + " :" + exp.split(":")[1]
    return sched


def _is_delayed(svc):
    """A revised time, or LDBWS's bare "Delayed" (late, no estimate yet) - as the Pixoo treats it."""
    exp = svc.get("expected") or ""
    return exp == "Delayed" or (":" in exp and exp != (svc.get("time") or ""))


def _status_colour(svc):
    """Amber on time, orange delayed, red cancelled - matching the Pixoo renderer."""
    if svc.get("is_cancelled"):
        return RED
    return ORANGE if _is_delayed(svc) else AMBER


def _right_text(svc):
    """Right-hand block: platform + time, like the Heltec ('P2 14:55' / 'P2 14:55 :58').

    Cancelled shows just 'cancelled'; the red colour already flags it.
    """
    if svc.get("is_cancelled"):
        return "cancelled"
    p = svc.get("platform")
    return (("P" + p + " ") if p else "") + _disp_time(svc)


def _draw(wri, x, y, s):
    Writer.set_textpos(wri.device, y, x)
    wri.printstring(s, False)  # lit pixels = 1 -> foreground colour at blit time


# --- A 1-bpp drawing strip that Writer renders into, then blitted to the TFT in colour ---

class Strip(framebuf.FrameBuffer):
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self._stride = (width + 7) // 8
        self._buf = bytearray(self._stride * height)
        super().__init__(self._buf, width, height, framebuf.MONO_HLSB)


class Board:
    """Renders the split board to the portrait TFT via 1-bpp strips + per-region change detection."""

    def __init__(self, display):
        self.d = display
        w = display.width
        sh = FONT.height() + 2                # strip height (must exceed font height)
        self.SSTRIP = sh
        # Layout (pixels): header + separator, then two EQUAL sections (north on top, south below),
        # each a title row followed by up to ROWS service rows, with a divider between them. On the
        # 240x320 panel: sections at y=22 / y=171, 6 rows each, divider at y=169.
        self.SEP1_Y = sh
        body = sh + 2
        half = (display.height - body) // 2
        self.SECTION_Y = (body, body + half)  # (north, south)
        self.DIV_Y = body + half - 2
        self.PITCH = sh
        self.ROWS_OFF = sh + 2                # first service row's offset below its section title
        self.ROWS = (half - self.ROWS_OFF) // self.PITCH

        self.strip = Strip(w, sh)             # every region is one font-height strip
        self.wri = self._mk(self.strip, FONT)
        self._rgb = bytearray(w * sh * 2)     # reused RGB565 scratch for one strip
        self._cache = {}     # slot -> (mono bytes, colour) for change detection
        self._status = None  # last status-screen lines (None while a board is shown)

    @staticmethod
    def _mk(strip, font):
        wri = Writer(strip, font, verbose=False)
        wri.set_clip(True, True, False)  # row_clip, col_clip, no wrap
        return wri

    # --- colourise a 1-bpp strip to RGB565 and push it ---

    def blit_strip(self, strip, x, y, colour):
        """Expand the strip's lit pixels to `colour` (unlit -> black) and block() it out.

        block() wants big-endian RGB565 (hi-then-lo), row-major across the portrait window. The
        1-bpp source is MONO_HLSB (bit 0x80>>col%8 of byte col//8).
        """
        w = strip.width
        h = strip.height
        rgb = self._rgb
        hi = colour >> 8
        lo = colour & 0xFF
        buf = strip._buf
        stride = strip._stride
        i = 0
        for row in range(h):
            base = row * stride
            for col in range(w):
                if buf[base + (col >> 3)] & (0x80 >> (col & 7)):
                    rgb[i] = hi
                    rgb[i + 1] = lo
                else:
                    rgb[i] = 0
                    rgb[i + 1] = 0
                i += 2
        self.d.block(x, y, x + w - 1, y + h - 1, memoryview(rgb)[: w * h * 2])

    def _emit(self, slot, strip, y, colour, force):
        """Blit a strip at x=0,y only if its pixels/colour changed since last time (or force)."""
        snap = bytes(strip._buf)
        prev = self._cache.get(slot)
        if not force and prev is not None and prev[0] == snap and prev[1] == colour:
            return
        self.blit_strip(strip, 0, y, colour)
        self._cache[slot] = (snap, colour)

    def clear(self):
        self.d.clear(BG)
        self._cache = {}

    # --- rendering ---

    def _header(self, data):
        strip = self.strip
        wri = self.wri
        strip.fill(0)
        gen = data.get("generated_at") or ""
        clock = gen.split("T")[1][:5] if "T" in gen else ""
        cw = wri.stringlen(clock) if clock else 0
        # A small "refreshing" hourglass appears left of the clock while the server is fetching
        # fresh data (data["stale"]). Aligned to the digits' band [0, baseline) - not the full cell
        # height, which has empty descender space. It changes the header strip's bytes, so the
        # change detection re-blits the header only when it toggles - not on every poll.
        stale = bool(data.get("stale"))
        base = wri.font.baseline()
        ih = base - 2
        iy = (base - ih) // 2
        icon_w = (ih + 4) if stale else 0
        head = data.get("station") or data.get("crs") or "RailInfo"
        _draw(wri, 0, 0, _fit_px(wri, head, strip.width - cw - 6 - icon_w))
        if clock:
            _draw(wri, strip.width - cw, 0, clock)
        if stale:
            self._hourglass(strip, strip.width - cw - 4 - ih, iy, ih)

    @staticmethod
    def _hourglass(strip, x, y, size):
        """Draw an hourglass (two bars + a crossed X) into a 1-bpp strip - the refreshing glyph."""
        s = size - 1
        strip.hline(x, y, size, 1)
        strip.hline(x, y + s, size, 1)
        strip.line(x, y, x + s, y + s, 1)
        strip.line(x + s, y, x, y + s, 1)

    @staticmethod
    def _arrow(strip, x, y, rows, up):
        """Draw a filled triangle pointing up or down (the section-title marker) - row k of the
        point is 2k+1 dots wide, so it is 2*rows-1 wide at its base."""
        for k in range(rows):
            strip.hline(x + rows - 1 - k, (y + k) if up else (y + rows - 1 - k), 2 * k + 1, 1)

    def _row(self, strip, wri, svc):
        """Draw one departure row into a (pre-cleared) strip: destination left, block right."""
        right = _right_text(svc)
        right_w = wri.stringlen(right)
        label = svc.get("destination") or svc.get("destination_crs") or "?"
        _draw(wri, 0, 0, _fit_px(wri, label, strip.width - right_w - 4))
        _draw(wri, strip.width - right_w, 0, right)

    def _section(self, key, y0, title, up, services, force):
        """One half: its title row (triangle + title), then up to ROWS rows - or "No trains"."""
        strip = self.strip
        strip.fill(0)
        self._arrow(strip, 0, (self.wri.font.baseline() - ARROW_ROWS) // 2, ARROW_ROWS, up)
        _draw(self.wri, 2 * ARROW_ROWS + 5, 0, title)
        self._emit((key, "t"), strip, y0, TITLE_C, force)
        n = len(services)
        for i in range(self.ROWS):
            strip.fill(0)
            colour = AMBER
            if i < n:
                self._row(strip, self.wri, services[i])
                colour = _status_colour(services[i])
            elif i == 0:
                _draw(self.wri, 0, 0, "No trains")
            self._emit((key, i), strip, y0 + self.ROWS_OFF + i * self.PITCH, colour, force)

    def render_split(self, data, force):
        if force:
            self.clear()
            self.d.fill_rectangle(0, self.SEP1_Y, self.d.width, 1, SEP_C)
            self.d.fill_rectangle(0, self.DIV_Y, self.d.width, 1, SEP_C)
        self._status = None
        self._header(data)
        self._emit("hdr", self.strip, 0, HEADER_C, force)
        self._section("n", self.SECTION_Y[0], NORTH_TITLE, True,
                      data.get("northbound") or [], force)
        self._section("s", self.SECTION_Y[1], SOUTH_TITLE, False,
                      data.get("southbound") or [], force)

    def show_status(self, lines):
        """Full-screen transient notice (WiFi/startup/error). Cached so it won't re-flicker."""
        if self._status == lines:
            return
        self.clear()
        self._status = lines
        y = 10
        for ln in lines:
            self.strip.fill(0)
            w = self.wri.stringlen(ln)
            x = max(0, (self.d.width - w) // 2)
            _draw(self.wri, x, 0, ln)
            self.blit_strip(self.strip, 0, y, AMBER)
            y += self.SSTRIP + 6


# --- Networking (ported from the Heltec client) ---

def connect_wifi(board):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    for attempt in range(1, WIFI_MAX_ATTEMPTS + 1):
        if wlan.isconnected():
            return wlan
        board.show_status(["RailInfo", "WiFi {}/{}".format(attempt, WIFI_MAX_ATTEMPTS)])
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


# --- Main loop ---

def run():
    display, _ = init_display()
    board = Board(display)

    while True:
        wlan = connect_wifi(board)
        if not wlan:
            board.show_status(["RailInfo", "WiFi failed", "Retrying..."])
            time.sleep(WIFI_FAIL_SLEEP_S)
            continue

        force = True   # full repaint on entry and after any status screen
        fails = 0
        while True:
            # The whole body is guarded: a transient render/socket error must NEVER escape run()
            # (that would leave the panel frozen). On error we log it, free memory, and keep
            # looping. `break`/`continue` below act on this while (they're not exceptions).
            try:
                try:
                    data = http_get_json(SERVER_URL + "?view=split")
                    fails = 0
                except Exception as exc:
                    fails += 1
                    print("fetch failed:", exc)
                    if not wlan.isconnected():
                        break
                    if fails >= FETCH_FAIL_LIMIT:
                        board.show_status(["RailInfo", "Server error"])
                        force = True
                    time.sleep(POLL_INTERVAL_S)
                    continue

                if data.get("status") == "starting":
                    board.show_status(["RailInfo", "Starting up..."])
                    force = True
                elif "northbound" not in data:
                    # A server without the split view falls back to `departures` (one list).
                    board.show_status(["RailInfo", "Server needs", "the split view"])
                    force = True
                else:
                    board.render_split(data, force)
                    force = False

                gc.collect()  # keep the heap defragmented each poll (no PSRAM)
                time.sleep(POLL_INTERVAL_S)
                if not wlan.isconnected():
                    break
            except Exception as exc:
                print("loop error:", exc)
                sys.print_exception(exc)
                gc.collect()
                force = True  # repaint fully next time
                if not wlan.isconnected():
                    break
                time.sleep(2)


if __name__ == "__main__":
    run()
