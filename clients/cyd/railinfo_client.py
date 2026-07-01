# railinfo_client.py - RailInfo hybrid client for the CYD (ESP32-2432S028), MicroPython.
#
# A HYBRID of the two existing RailInfo clients:
#   * multi-screen PULL, like the Heltec e-ink client - connects to WiFi, polls the RailInfo
#     --serve JSON API (/board) every few seconds, and cycles three views (departures / all /
#     arrivals) on a button/tap.
#   * COLOUR DOT-MATRIX look, like the Pixoo - amber-on-black National-Rail styling with
#     per-row status colours (amber on time, orange delayed, red cancelled).
#
# Rendering (memory-driven): this is an original ESP32 with NO PSRAM, so a full 320x240 RGB565
# framebuffer (150 KB) will not fit. Instead each region (header, each row, footer) is drawn
# with Peter Hinch's Writer into a small 1-bpp `Strip` framebuffer, then colourised to RGB565
# and pushed to the TFT via the ILI9341 driver's block(). This reuses the exact Dot Matrix font
# pipeline (dotmatrix17/27 + writer.py) the Heltec uses. Per-region change detection means only
# regions whose pixels actually changed get re-blitted, so a static board doesn't flicker.
#
# Input is HYBRID too: the BOOT button (GPIO0) AND a screen tap (the XPT2046 touch IRQ line,
# GPIO36) both feed one debounced latch via a pin IRQ - either advances the view. No touch SPI
# reads or coordinate maths are needed for "tap to cycle".
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

import framebuf
from machine import Pin, SoftSPI

from config import WIFI_SSID, WIFI_PASSWORD, SERVER_URL
try:
    from config import POLL_INTERVAL_S
except ImportError:
    POLL_INTERVAL_S = 5

from boards import init_display
from ili9341 import color565
from writer import Writer
import dotmatrix19

# --- Font + scaling ---
# The dot-matrix TTF only rasterises crisply (dots on whole pixels) at small sizes on this sharp
# TFT — 19 is clean, 22-38 are not. So there's ONE font (dotmatrix19, as on the Heltec), and the
# big departure rows are drawn at 19 then INTEGER-scaled x2 at blit time (each dot becomes a 2x2
# block, staying perfectly square). Small text (header/footer/lists) is 19 at 1x.
SMALL_FONT = dotmatrix19
BIG_SCALE = 2

# Calling-at footer scroll (departures view): pixels per tick and the tick interval (ms). The
# footer only scrolls when the text is wider than the screen; ~50 px/s reads comfortably.
# INPUT_POLL_MS is decoupled from (and much shorter than) the scroll tick so button/tap polling
# isn't starved by the ~50ms footer blit — otherwise ~half of presses were missed while scrolling.
FOOT_SCROLL_STEP = 8
FOOT_SCROLL_MS = 60
INPUT_POLL_MS = 15
FOOT_SCROLL_DELAY_MS = 1500  # hold the start of the calling list still this long before scrolling

# --- Colours (RGB565) - amber/orange/red, tuned for THIS panel ---
# The CYD's TFT has a very luminous green, so the Pixoo's yellowish amber (255,176,0) reads
# green here — and thin coloured TEXT skews greener than solid fills. These were tuned on-panel
# as rendered text: amber on-time stays warm, delayed is a deep orange (not green), cancelled a
# clean red. Green levels 150 / 60 / 0 keep the three states unmistakably distinct.
BG = 0x0000
AMBER = color565(255, 150, 0)
ORANGE = color565(255, 60, 0)
RED = color565(255, 0, 0)
HEADER_C = AMBER
SEP_C = color565(90, 90, 90)

# --- Timing / behaviour (mirrors the Heltec client) ---
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
    exp = svc.get("expected") or ""
    return ":" in exp and exp != (svc.get("time") or "")


def _status_colour(svc):
    """Amber on time, orange delayed, red cancelled - matching the Pixoo renderer."""
    if svc.get("is_cancelled"):
        return RED
    return ORANGE if _is_delayed(svc) else AMBER


def _right_text(svc):
    """Right-hand block: platform + time, like the Heltec ('P2 14:55' / '2 14:55 :58').

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
    """Renders departure boards to the colour TFT via 1-bpp strips + per-region change detection."""

    def __init__(self, display):
        self.d = display
        w = display.width
        sh = SMALL_FONT.height() + 2          # small strip height (must exceed font height)
        self.SSTRIP = sh                      # small row displayed height (scale 1)
        self.BIG_DISP = sh * BIG_SCALE        # big departure row displayed height (scale 2)
        # Layout (pixels).
        self.SEP1_Y = sh
        self.DEP_ROWS_Y = sh + 4
        self.DEP_PITCH = self.BIG_DISP + 3
        self.DEP_MAX_ROWS = 4                 # 2x-scaled rows are ~42px tall, so 4 fit + footer
        self.LIST_ROWS_Y = sh + 3
        self.LIST_PITCH = sh
        self.FOOT_Y = display.height - sh - 1
        self.LIST_MAX_ROWS = (self.FOOT_Y - self.LIST_ROWS_Y) // self.LIST_PITCH

        self.small = Strip(w, sh)             # header / footer / list rows (dotmatrix19, scale 1)
        self.big = Strip(w // BIG_SCALE, sh)  # departure-row SOURCE (scale 2 -> full width)
        self.wri_small = self._mk(self.small, SMALL_FONT)
        self.wri_big = self._mk(self.big, SMALL_FONT)
        self._rgb = bytearray(w * self.BIG_DISP * 2)  # reused RGB565 scratch (largest output)
        self._cache = {}     # slot -> (mono bytes, colour) for change detection
        self._status = None  # last status-screen lines (None while a board is shown)
        self._foot_key = None    # last footer text (rebuild the wide strip only when it changes)
        self._scrolling = False  # is the footer currently wider than the screen (scroll it)?
        self._scroll = 0         # current horizontal scroll offset (px)
        self._scroll_start = 0   # ticks_ms when the current footer was built (for the start pause)
        self._foot_wide = None   # Strip holding the full footer text (for scrolling)
        self._foot_total = 0     # width of _foot_wide incl. wrap gap

    @staticmethod
    def _mk(strip, font):
        wri = Writer(strip, font, verbose=False)
        wri.set_clip(True, True, False)  # row_clip, col_clip, no wrap
        return wri

    # --- colourise a 1-bpp strip to RGB565 (optionally integer-scaled) and push it ---

    def blit_strip(self, strip, x, y, colour, scale=1):
        """Expand the strip's lit pixels to `colour` (unlit -> black) and block() it out, with
        optional NxN integer upscaling (each source dot -> a scale x scale block, kept square).

        block() wants big-endian RGB565 (hi-then-lo), emitted row-major — how the ILI9342 fills
        its native-landscape window. The 1-bpp source is MONO_HLSB (bit 0x80>>col%8 of byte col//8).
        """
        w = strip.width
        h = strip.height
        rgb = self._rgb
        hi = colour >> 8
        lo = colour & 0xFF
        buf = strip._buf
        stride = strip._stride
        if scale == 1:
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
            return
        ow = w * scale
        if ow > self.d.width - x:
            ow = self.d.width - x
        oh = h * scale
        n = ow * oh * 2
        for k in range(n):          # clear to black; lit blocks are painted below
            rgb[k] = 0
        for row in range(h):
            base = row * stride
            orow = row * scale
            for col in range(w):
                if buf[base + (col >> 3)] & (0x80 >> (col & 7)):
                    bx = col * scale
                    if bx >= ow:
                        continue
                    for dy in range(scale):
                        rbase = (orow + dy) * ow
                        for dx in range(scale):
                            ox = bx + dx
                            if ox < ow:
                                idx = (rbase + ox) * 2
                                rgb[idx] = hi
                                rgb[idx + 1] = lo
        self.d.block(x, y, x + ow - 1, y + oh - 1, memoryview(rgb)[:n])

    def _emit(self, slot, strip, y, colour, force, scale=1):
        """Blit a strip at x=0,y only if its pixels/colour changed since last time (or force)."""
        snap = bytes(strip._buf)
        prev = self._cache.get(slot)
        if not force and prev is not None and prev[0] == snap and prev[1] == colour:
            return
        self.blit_strip(strip, 0, y, colour, scale)
        self._cache[slot] = (snap, colour)

    def clear(self):
        self.d.clear(BG)
        self._cache = {}

    # --- scrolling calling-at footer ---

    def _set_footer(self, text, force):
        """Prepare the footer for `text`: static if it fits, else a wide strip to scroll.

        Only rebuilt when the text changes (or on a forced full repaint), so scrolling isn't
        reset every poll when the board is unchanged.
        """
        if text == self._foot_key and not force:
            return
        self._foot_key = text
        total = self.wri_small.stringlen(text) if text else 0
        if total <= self.d.width:                       # fits — draw once, no scroll
            self._scrolling = False
            self._foot_wide = None
            self.small.fill(0)
            if text:
                _draw(self.wri_small, 0, 0, text)
            self._emit("foot", self.small, self.FOOT_Y, AMBER, True)
            return
        gap = 30                                         # blank run before the text wraps
        wide = Strip(total + gap, self.small.height)
        wri = self._mk(wide, SMALL_FONT)
        wide.fill(0)
        Writer.set_textpos(wide, 0, 0)
        wri.printstring(text, False)
        self._foot_wide = wide
        self._foot_total = total + gap
        self._scrolling = True
        self._scroll = 0
        self._scroll_start = time.ticks_ms()  # start the pause; tick_scroll holds until it elapses
        self.blit_footer(self._scroll)

    def blit_footer(self, scroll):
        """Blit the screen-width window of the wide footer at horizontal offset `scroll`.

        Two `framebuf.blit`s (fast C) paint the visible slice and its wrap-around tail into the
        reused `small` strip, then one `blit_strip` colourises it into the footer row.
        """
        off = scroll % self._foot_total
        self.small.fill(0)
        self.small.blit(self._foot_wide, -off, 0)
        self.small.blit(self._foot_wide, self._foot_total - off, 0)
        self.blit_strip(self.small, 0, self.FOOT_Y, AMBER)

    def tick_scroll(self):
        """Advance + redraw the footer one scroll step, after an initial hold so the start of the
        list is readable. No-op unless the footer is scrolling and the start pause has elapsed."""
        if self._scrolling and time.ticks_diff(time.ticks_ms(), self._scroll_start) >= FOOT_SCROLL_DELAY_MS:
            self._scroll += FOOT_SCROLL_STEP
            self.blit_footer(self._scroll)

    # --- rendering ---

    def _header(self, title, data):
        strip = self.small
        wri = self.wri_small
        strip.fill(0)
        gen = data.get("generated_at") or ""
        clock = gen.split("T")[1][:5] if "T" in gen else ""
        cw = wri.stringlen(clock) if clock else 0
        head = title or data.get("station") or data.get("crs") or "RailInfo"
        _draw(wri, 0, 0, _fit_px(wri, head, strip.width - cw - 6))
        if clock:
            _draw(wri, strip.width - cw, 0, clock)

    def _row(self, strip, wri, svc):
        """Draw one departure/arrival row into a (pre-cleared) strip: label left, block right.

        Right-justified against strip.width — which for the scaled departure rows is the SOURCE
        width (half the panel), so it lands correctly once blitted at 2x.
        """
        right = _right_text(svc)
        right_w = wri.stringlen(right)
        label = svc.get("destination") or svc.get("destination_crs") or "?"
        _draw(wri, 0, 0, _fit_px(wri, label, strip.width - right_w - 4))
        _draw(wri, strip.width - right_w, 0, right)

    def render_departures(self, data, force):
        if force:
            self.clear()
            self.d.fill_rectangle(0, self.SEP1_Y, self.d.width, 1, SEP_C)
            self.d.fill_rectangle(0, self.FOOT_Y - 2, self.d.width, 1, SEP_C)
        self._status = None
        self._header(None, data)
        self._emit("hdr", self.small, 0, HEADER_C, force)

        services = data.get("services") or []
        n = len(services)
        for i in range(self.DEP_MAX_ROWS):
            y = self.DEP_ROWS_Y + i * self.DEP_PITCH
            self.big.fill(0)
            colour = AMBER
            if i < n:
                self._row(self.big, self.wri_big, services[i])
                colour = _status_colour(services[i])
            elif i == 0 and n == 0:
                _draw(self.wri_big, 0, 0, "No trains")
            self._emit(("r", i), self.big, y, colour, force, BIG_SCALE)

        # Footer: the calling-at line for the first useful train (server supplies it). If it's
        # wider than the screen it scrolls (animated between polls by tick_scroll); otherwise it's
        # drawn once, statically.
        ca = data.get("calling_at") or []
        self._set_footer(("Calling: " + ", ".join(ca)) if ca else "", force)

    def render_list(self, title, data, force):
        if force:
            self.clear()
            self.d.fill_rectangle(0, self.SEP1_Y, self.d.width, 1, SEP_C)
        self._status = None
        self._scrolling = False  # list views have no scrolling footer
        self._header(title, data)
        self._emit("hdr", self.small, 0, HEADER_C, force)

        services = data.get("services") or []
        n = len(services)
        for i in range(self.LIST_MAX_ROWS):
            y = self.LIST_ROWS_Y + i * self.LIST_PITCH
            self.small.fill(0)
            colour = AMBER
            if i < n:
                self._row(self.small, self.wri_small, services[i])
                colour = _status_colour(services[i])
            elif i == 0 and n == 0:
                _draw(self.wri_small, 0, 0, "No services")
            self._emit(("r", i), self.small, y, colour, force)

    def show_status(self, lines):
        """Full-screen transient notice (WiFi/startup/error). Cached so it won't re-flicker."""
        if self._status == lines:
            return
        self.clear()
        self._status = lines
        self._scrolling = False
        y = 10
        for ln in lines:
            self.small.fill(0)
            w = self.wri_small.stringlen(ln)
            x = max(0, (self.d.width - w) // 2)
            _draw(self.wri_small, x, 0, ln)
            self.blit_strip(self.small, 0, y, AMBER)
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


# --- View modes, cycled by the button/tap: (view query, is_list, header title) ---
MODES = (
    ("departures", False, None),
    ("all", True, "All departures"),
    ("arrivals", True, "Arrivals"),
)

# Inputs are POLLED, not interrupt-driven. On this CYD the XPT2046 touch IRQ line (GPIO36) is
# unusable — it fires ~9x/s spuriously and a real tap doesn't pull it low — and the GPIO0 IRQ
# never fired either. Polling works reliably: the BOOT button by GPIO0 LEVEL, and a screen tap by
# READING the XPT2046's pressure over its own SoftSPI bus. A "press" is a fresh high->low on the
# button or a fresh touch (pressure crossing the threshold), time-debounced. (Trade-off vs the
# Heltec's IRQ: a tap that starts and ends entirely within the ~1s blocking fetch can be missed;
# polling covers the ~5s wait, which is almost all of each cycle.)
PRESS_DEBOUNCE_MS = 300
TOUCH_Z_THRESH = 400   # XPT2046 Z1 reads ~0 untouched, several hundred+ when pressed


class Inputs:
    def __init__(self, cfg):
        self.btn = Pin(cfg["button"], Pin.IN, Pin.PULL_UP)
        self.tspi = SoftSPI(baudrate=1_000_000, polarity=0, phase=0,
                            sck=Pin(cfg["touch_sck"]), mosi=Pin(cfg["touch_mosi"]),
                            miso=Pin(cfg["touch_miso"]))
        self.tcs = Pin(cfg["touch_cs"], Pin.OUT, value=1)
        self._pb = 1          # previous button level (1 = released)
        self._touch = False   # previous touch state
        self._last_ms = 0

    def _z1(self):
        """XPT2046 Z1 pressure sample (0..4095); ~0 when untouched."""
        self.tcs(0)
        self.tspi.write(b"\xb0")       # Z1 measurement command
        r = self.tspi.read(2)
        self.tcs(1)
        return ((r[0] << 8) | r[1]) >> 3

    def pressed(self):
        """True on a fresh BOOT press or a fresh screen tap (edge-triggered, debounced)."""
        hit = False
        vb = self.btn.value()
        if vb == 0 and self._pb == 1:      # button just went down
            hit = True
        self._pb = vb
        touching = self._z1() > TOUCH_Z_THRESH
        if touching and not self._touch:   # screen just touched
            hit = True
        self._touch = touching
        if hit:
            now = time.ticks_ms()
            if time.ticks_diff(now, self._last_ms) > PRESS_DEBOUNCE_MS:
                self._last_ms = now
                return True
        return False

    def wait(self, secs, on_tick=None):
        """Poll up to `secs`; return True as soon as a press/tap is seen, else False.

        Input is polled every INPUT_POLL_MS; `on_tick` (the footer scroller) fires only every
        FOOT_SCROLL_MS, with an extra input poll right after it — so the ~50ms footer blit can't
        swallow a press.
        """
        end = time.ticks_add(time.ticks_ms(), int(secs * 1000))
        next_tick = time.ticks_ms()
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            if self.pressed():
                return True
            if on_tick is not None and time.ticks_diff(time.ticks_ms(), next_tick) >= 0:
                on_tick()
                next_tick = time.ticks_add(time.ticks_ms(), FOOT_SCROLL_MS)
                if self.pressed():          # poll again immediately after the blit
                    return True
            time.sleep_ms(INPUT_POLL_MS)
        return False


# --- Main loop ---

def run():
    display, cfg = init_display()
    board = Board(display)
    inputs = Inputs(cfg)
    mode = 0

    while True:
        wlan = connect_wifi(board)
        if not wlan:
            board.show_status(["RailInfo", "WiFi failed", "Retrying..."])
            time.sleep(WIFI_FAIL_SLEEP_S)
            continue

        force = True   # force a full repaint on entry and after a mode change
        fails = 0
        pending = False  # a press/tap seen during the last wait, handled at the loop top
        while True:
            if pending or inputs.pressed():  # BOOT or tap -> next view now
                mode = (mode + 1) % len(MODES)
                force = True
                pending = False
                print("mode ->", MODES[mode][0])

            view, is_list, title = MODES[mode]
            try:
                data = http_get_json(SERVER_URL + "?view=" + view)
                fails = 0
            except Exception as exc:
                fails += 1
                print("fetch failed:", exc)
                if not wlan.isconnected():
                    break
                if fails >= FETCH_FAIL_LIMIT:
                    board.show_status(["RailInfo", "Server error"])
                    force = True
                pending = inputs.wait(POLL_INTERVAL_S, board.tick_scroll)
                continue

            if data.get("status") == "starting":
                board.show_status(["RailInfo", "Starting up..."])
                force = True
            elif is_list:
                board.render_list(title, data, force)
                force = False
            else:
                board.render_departures(data, force)
                force = False

            pending = inputs.wait(POLL_INTERVAL_S, board.tick_scroll)
            if not wlan.isconnected():
                break


if __name__ == "__main__":
    run()
