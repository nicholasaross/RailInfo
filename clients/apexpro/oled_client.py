"""RailInfo → SteelSeries Apex Pro TKL OLED client (a GameSense pull client).

Another pull client, in the mould of the Heltec/CYD/NM-TV ones, but running **host-side**
on the Windows box rather than on an ESP32: it polls the RailInfo JSON server's ``/board``
endpoint and renders the northbound board onto the Apex Pro TKL's 128×40 monochrome OLED
via SteelSeries **GameSense**.

GameSense is a small local HTTP/JSON server that SteelSeries GG runs on this machine. We:

1. discover its address from ``%PROGRAMDATA%\\SteelSeries\\SteelSeries Engine 3\\coreProps.json``;
2. register an app (``game_metadata``);
3. bind a *screen* handler for the ``screened-128x40`` device — three text lines fed by
   context-frame keys (``bind_game_event``);
4. poll RailInfo, format the top two departures + a scrolling "calling at…" marquee, and
   push it with ``game_event``. Each event also resets GameSense's ~15 s deregistration
   timer, so the display stays owned by us while the loop runs.

The upstream board is re-fetched on its own slower cadence (``--data-interval``) and reused
between pushes, so the marquee can scroll smoothly without hammering the RailInfo server —
the same decoupling the Pixoo streamer uses. A failed fetch keeps the last good board.

Runs on the venv's httpx only (no ``railinfo`` import — it's decoupled over HTTP, exactly
like the on-device clients)::

    uv run python clients/apexpro/oled_client.py                 # localhost RailInfo + GG
    uv run python clients/apexpro/oled_client.py --railinfo-host 192.168.1.50:8000
    uv run python clients/apexpro/oled_client.py --once          # one frame then exit

Needs SteelSeries GG running, and a RailInfo server (``uv run python -u main.py --serve``).
The 128×40 mono OLED is on the "Legacy" Apex Pro TKL (2020/2023); the Gen 3's colour screen
uses a different device type and is not targeted here.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

import render  # sibling module (the script's own dir is on sys.path when run directly)

# --- GameSense app identity -------------------------------------------------------------
GAME = "RAILINFO"                 # uppercase A-Z/0-9/_/- ; our namespace on the GG server
GAME_DISPLAY = "RailInfo Departures"
DEVELOPER = "RailInfo"
EVENT = "BOARD"                   # the one event whose handler draws the screen
DEVICE_TYPE = "screened-128x40"  # Legacy Apex Pro TKL OLED
IMAGE_KEY = "image-data-128x40"  # per-frame bitmap key GameSense expects for this device

# ~21 fixed-width glyphs fit across 128 px in GameSense's default screen font. Tunable via
# --line-chars if your firmware renders them a little wider/narrower.
DEFAULT_LINE_CHARS = 21


class GameSenseError(RuntimeError):
    """A friendly, user-facing error for a GameSense/SteelSeries GG problem."""


def gamesense_base_url() -> str:
    """Read the local GameSense server address that SteelSeries GG publishes on startup."""
    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    core = Path(program_data) / "SteelSeries" / "SteelSeries Engine 3" / "coreProps.json"
    if not core.is_file():
        raise GameSenseError(
            f"coreProps.json not found at {core}. Is SteelSeries GG installed and running?"
        )
    try:
        address = json.loads(core.read_text(encoding="utf-8"))["address"]
    except (ValueError, KeyError) as exc:
        raise GameSenseError(f"Could not parse {core}: {exc}") from exc
    return f"http://{address}"


class GameSense:
    """GameSense client that discovers the server lazily and reconnects on connection loss.

    SteelSeries GG rewrites its GameSense port in ``coreProps.json`` while it starts up (and on
    restarts), so a long-lived client can't cache one address: a push to a stale port fails with
    connection-refused. So this connects lazily via :meth:`ensure` — (re)reading the address and
    re-registering — and :meth:`show` marks the connection dropped on any transport error, so the
    run loop just re-ensures and carries on. Mirrors the Pixoo runner's connect-factory pattern
    (see CLAUDE.md: the loop owns the device lifecycle and never dies because the device did).
    """

    def __init__(self, *, bitmap: bool, timeout: float = 5.0) -> None:
        self._bitmap = bitmap
        self._timeout = timeout
        self._http: httpx.Client | None = None

    @property
    def connected(self) -> bool:
        return self._http is not None

    def ensure(self) -> None:
        """Connect (read the current address) and register+bind, if not already connected.

        Raises :class:`GameSenseError` if GG is unreachable so the caller can back off and retry.
        """
        if self._http is not None:
            return
        self._http = httpx.Client(base_url=gamesense_base_url(), timeout=self._timeout)
        try:
            self._register()
        except GameSenseError:
            self.drop()  # a failed register leaves no usable connection; force a clean retry
            raise

    def drop(self) -> None:
        """Tear down the current connection so the next :meth:`ensure` reconnects fresh."""
        if self._http is not None:
            self._http.close()
            self._http = None

    def _post(self, path: str, payload: dict) -> None:
        if self._http is None:
            raise GameSenseError("not connected")
        try:
            self._http.post(path, json=payload).raise_for_status()
        except httpx.HTTPError as exc:
            raise GameSenseError(f"GameSense {path} failed: {exc}") from exc

    def _register(self, *, line_count: int = 3) -> None:
        """Register the app and bind the screen handler for the configured mode.

        Bitmap mode binds a full-screen image handler (``has-text: false``) we feed a fresh
        128×40 bitmap each frame via the ``image-data-128x40`` context-frame key; otherwise it
        binds GameSense's built-in multi-line text handler (which only fits ~2 lines here).
        """
        bitmap = self._bitmap
        self._post(
            "/game_metadata",
            {
                "game": GAME,
                "game_display_name": GAME_DISPLAY,
                "developer": DEVELOPER,
                # Auto-deregister if we stop sending events (safety net if the loop dies).
                "deinitialize_timer_length_ms": 15000,
            },
        )
        if bitmap:
            # A full-size (640-byte) blank default; the live bytes arrive per-event via the
            # image-data-128x40 context-frame key. GG rejects an empty image-data array (500).
            datas = [{"has-text": False, "image-data": [0] * (render.WIDTH * render.HEIGHT // 8)}]
        else:
            datas = [
                {
                    "lines": [
                        {"has-text": True, "context-frame-key": f"l{i}", "wrap": 0}
                        for i in range(line_count)
                    ]
                }
            ]
        self._post(
            "/bind_game_event",
            {
                "game": GAME,
                "event": EVENT,
                "value_optional": True,
                "handlers": [
                    {
                        "device-type": DEVICE_TYPE,
                        "mode": "screen",
                        "zone": "one",
                        "datas": datas,
                    }
                ],
            },
        )

    def show(self, frame: dict) -> None:
        """Push one screen frame (text keys, or the image-data array) and reset the GG timer.

        On any transport error the connection is dropped so the next :meth:`ensure` reconnects
        (picking up a fresh port if GG moved it); the error is re-raised for the caller to log.
        """
        try:
            self._post("/game_event", {"game": GAME, "event": EVENT, "data": {"frame": frame}})
        except GameSenseError:
            self.drop()
            raise

    def remove(self) -> None:
        """Deregister the app so GG hands the screen back to its normal content (best-effort)."""
        if self._http is None:
            return
        try:
            self._post("/remove_game", {"game": GAME})
        except GameSenseError:
            pass  # best-effort on shutdown

    def close(self) -> None:
        self.drop()


# --- Board formatting -------------------------------------------------------------------

def _status_suffix(svc: dict) -> str:
    """Trailing status token: '' on time, ' CANC' cancelled, else the revised time.

    Mirrors the Pixoo/e-ink notation: an on-time service shows nothing, a delayed one shows
    its expected ``HH:MM``, and a cancellation shows ``CANC``.
    """
    expected = (svc.get("expected") or "").strip()
    if svc.get("is_cancelled") or expected.lower() == "cancelled":
        return " CANC"
    if expected and expected.lower() != "on time":
        return f" {expected}"
    return ""


def _departure_line(svc: dict, width: int) -> str:
    """``HH:MM Destination`` + status, truncating the destination (never the time/status)."""
    head = f"{svc.get('time', '--:--')} "
    tail = _status_suffix(svc)
    room = max(width - len(head) - len(tail), 0)
    dest = (svc.get("destination") or "?")[:room]
    return f"{head}{dest}{tail}"[:width]


def _calling_text(board: dict) -> str:
    """The 'Calling at:' string for the marquee, or a fallback message."""
    calling = board.get("calling_at") or []
    if calling:
        return "Calling at: " + ", ".join(calling)
    msgs = board.get("messages") or []
    return msgs[0] if msgs else ""


def build_frame(board: dict, *, width: int, marquee_offset: int) -> dict[str, str]:
    """Turn a ``/board`` payload into the 3-line screen frame."""
    if board.get("status") == "starting":
        crs = board.get("crs") or ""
        return {"l0": f"{crs} starting...".strip(), "l1": "", "l2": ""}

    services = board.get("services") or []
    if not services:
        return {"l0": "No departures", "l1": "", "l2": ""}
    l0 = _departure_line(services[0], width)
    l1 = _departure_line(services[1], width) if len(services) >= 2 else ""

    # Line 3: scroll the calling-at line if it overflows, else show it static.
    text = _calling_text(board)
    if len(text) <= width:
        l2 = text
    else:
        pad = text + "   "        # gap before it wraps around
        start = marquee_offset % len(pad)
        l2 = (pad + pad)[start:start + width]
    return {"l0": l0, "l1": l1, "l2": l2}


# --- Data fetch -------------------------------------------------------------------------

@dataclass
class RailInfo:
    """Polls the RailInfo JSON server's ``/board`` view, keeping the last good board."""

    base_url: str
    view: str = "departures"
    timeout: float = 5.0
    _last: dict | None = None

    def board(self) -> dict | None:
        """Fetch the current board; on failure return the last good one (or None)."""
        try:
            resp = httpx.get(
                f"{self.base_url}/board", params={"view": self.view}, timeout=self.timeout
            )
            resp.raise_for_status()
            self._last = resp.json()
        except (httpx.HTTPError, ValueError):
            pass  # keep last good board; the loop will retry next data-interval
        return self._last


# --- Main loop --------------------------------------------------------------------------

_RETRY_BACKOFF = 3.0   # seconds to wait after a GameSense outage before retrying
_ONCE_MAX_TRIES = 5    # give up --once after this many connect attempts


def run(args: argparse.Namespace) -> int:
    bitmap = not args.text
    mode = "bitmap" if bitmap else "text"
    railinfo = RailInfo(base_url=_normalise(args.railinfo_host), view=args.view)
    gs = GameSense(bitmap=bitmap)

    board: dict | None = None
    last_fetch = 0.0
    step = 0
    was_connected = False   # so we log connect/outage transitions once, not every frame
    tries = 0
    try:
        while True:
            now = time.monotonic()
            if board is None or now - last_fetch >= args.data_interval:
                board = railinfo.board()
                last_fetch = now
            try:
                gs.ensure()
                gs.show(_frame(board, step, args, bitmap))
                tries = 0
                if not was_connected:
                    print(f"Registered '{GAME}' with GameSense ({mode} mode); "
                          "streaming RailInfo -> Apex Pro OLED.")
                    was_connected = True
            except GameSenseError as exc:
                tries += 1
                if was_connected or tries == 1:
                    print(f"GameSense unavailable ({exc}); retrying every "
                          f"{_RETRY_BACKOFF:g}s (is SteelSeries GG running?).")
                was_connected = False
                if args.once and tries >= _ONCE_MAX_TRIES:
                    print("error: gave up after repeated GameSense failures.")
                    return 1
                time.sleep(_RETRY_BACKOFF)
                continue
            if args.once:
                return 0
            step += 1
            time.sleep(args.refresh)
    except KeyboardInterrupt:
        return 0
    finally:
        gs.remove()
        gs.close()
        print("\nStopped; released the OLED back to SteelSeries GG.")


def _frame(board: dict | None, step: int, args: argparse.Namespace, bitmap: bool) -> dict:
    """Build one screen frame for the current step (image bytes, or text keys)."""
    if bitmap:
        payload = board if board is not None else {"status": "starting"}
        return {IMAGE_KEY: render.frame_bytes(payload, rows=args.rows,
                                              stale=bool(payload.get("stale")))}
    if board is None:
        return {"l0": "RailInfo", "l1": "no data", "l2": ""}
    return build_frame(board, width=args.line_chars, marquee_offset=step)


def _normalise(host: str) -> str:
    """Accept 'host:port' or a full URL; return a scheme-qualified base URL."""
    return host if host.startswith(("http://", "https://")) else f"http://{host}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stream a RailInfo board to the Apex Pro TKL OLED.")
    p.add_argument(
        "--railinfo-host",
        default=os.environ.get("RAILINFO_HOST", "localhost:8000"),
        help="RailInfo server as host:port or URL (default: localhost:8000).",
    )
    p.add_argument("--view", default="departures", choices=("departures", "all", "arrivals"))
    p.add_argument(
        "--refresh", type=float, default=10.0,
        help="Screen push cadence, seconds (also the GameSense keep-alive; must be < 15).",
    )
    p.add_argument(
        "--data-interval", type=float, default=30.0,
        help="How often to re-fetch the board from RailInfo, seconds (default: 30).",
    )
    p.add_argument(
        "--rows", type=int, default=4,
        help="Bitmap mode: how many services to show (default: 4).",
    )
    p.add_argument(
        "--text", action="store_true",
        help="Use GameSense's built-in text handler instead of the bitmap renderer "
             "(fits only ~2 lines; bitmap is the default).",
    )
    p.add_argument("--line-chars", type=int, default=DEFAULT_LINE_CHARS,
                   help="Text mode only: glyphs per line.")
    p.add_argument("--once", action="store_true", help="Draw one frame and exit.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parse_args(argv))
    except GameSenseError as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
