"""HTTP server exposing the departure board(s) as JSON for LAN display clients.

Three views, selected with ``?view=``:

* ``departures`` (default) — the London-bound board with calling points (the Heltec's
  landscape view, and what the Pixoo shows).
* ``all`` — every departure, no direction filter (the Heltec's portrait view).
* ``arrivals`` — arriving services, labelled by origin (portrait view).

The server holds **no state until a client connects** — it never queries LDBWS eagerly at
startup. The first request for a view returns ``{"status": "starting", ...}`` immediately and
kicks off that view's fetch in the background; once it lands, subsequent polls get the real
board (``"status": "ready"``). Thereafter each view is refreshed lazily on a short TTL using
**stale-while-revalidate**: a caller always gets the current board straight away (even slightly
stale) while a single background refresh runs, so neither the HTTP clients nor an in-process
Pixoo loop ever block on LDBWS, and concurrent consumers never fan out into duplicate upstream
calls. A failed refresh keeps the last good board. Built from the stdlib only.

The cache (:class:`BoardCache`) stores the domain :class:`DepartureBoard`, not rendered JSON,
so one fetch can feed both this server (projected to JSON) and the Pixoo renderer (which
consumes the domain model) when they share a process — see ``main.py --serve --pixoo``.
"""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from railinfo.domain.models import DepartureBoard, Service
from railinfo.ldbws.client import LdbwsError
from railinfo.service import BoardService

log = logging.getLogger(__name__)

VIEWS = ("departures", "all", "arrivals")
LANDSCAPE_LIMIT = 6   # landscape board shows ~5
PORTRAIT_LIMIT = 25   # portrait list shows ~25


def _stops_index(services: list[Service]) -> int | None:
    """First non-cancelled service that has calling points, else None.

    Mirrors ``_choose_stops_index`` in :mod:`railinfo.renderers.pixoo`; replicated here so the
    server has no dependency on the Pillow image renderer.
    """
    return next(
        (i for i, s in enumerate(services) if not s.is_cancelled and s.calling_points),
        None,
    )


def _svc_dict(s: Service, arrivals: bool) -> dict:
    """Project one service. For arrivals, headline the arrival time and the origin."""
    if arrivals:
        time_ = s.sta or s.std or ""
        expected = "Cancelled" if s.is_cancelled else (s.eta or "On time")
        label = s.origin or s.destination or "?"
    else:
        time_ = s.time
        expected = s.expected
        label = s.destination or s.destination_crs or "?"
    return {
        "time": time_,
        "expected": expected,
        "destination": label,  # client renders this as the row label (origin for arrivals)
        "platform": s.platform,
        "is_cancelled": s.is_cancelled,
    }


def to_client_dict(
    board: DepartureBoard,
    limit: int = LANDSCAPE_LIMIT,
    *,
    arrivals: bool = False,
    with_calling: bool = False,
) -> dict:
    """Project a :class:`DepartureBoard` into the compact JSON a display client needs."""
    services = board.services[:limit]
    out = {
        "status": "ready",
        "station": board.location_name,
        "crs": board.crs,
        "generated_at": board.generated_at,
        "messages": list(board.nrcc_messages),
        "services": [_svc_dict(s, arrivals) for s in services],
    }
    if with_calling:
        idx = _stops_index(services)
        out["stops_index"] = idx
        out["calling_at"] = (
            [cp.location for cp in services[idx].calling_points] if idx is not None else []
        )
    return out


def _project(view: str, board: DepartureBoard) -> bytes:
    """Render the JSON body for ``view`` from a cached domain board."""
    if view == "arrivals":
        payload = to_client_dict(board, PORTRAIT_LIMIT, arrivals=True)
    elif view == "all":
        payload = to_client_dict(board, PORTRAIT_LIMIT)
    else:  # departures: the filtered, with-calling landscape board
        payload = to_client_dict(board, LANDSCAPE_LIMIT, with_calling=True)
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class BoardCache:
    """Caches the domain :class:`DepartureBoard` per view; one LDBWS fetch feeds all consumers.

    Lazy on connect: a view isn't fetched until first requested, and :meth:`get_board` returns
    ``None`` until that first fetch lands (the HTTP layer renders this as ``status:"starting"``).
    Thereafter it is **stale-while-revalidate**: callers get the cached board immediately and a
    single background refresh is launched per view when the TTL expires (coalesced via
    ``_inflight``, so the ~5 fps Pixoo poll can't fan out into duplicate upstream calls). A
    failed fetch keeps the last good board.
    """

    def __init__(
        self,
        service: BoardService,
        *,
        crs: str | None = None,
        board_kwargs: dict | None = None,
        ttl: float = 30.0,
    ) -> None:
        self._service = service
        self._crs = crs
        self._bk = board_kwargs or {}
        self._ttl = ttl
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[DepartureBoard, float]] = {}
        self._inflight: set[str] = set()  # views with a fetch running (refresh coalescing)
        self._started = False  # has any client connected yet?
        self.starting = json.dumps(
            {
                "status": "starting",
                "station": None,
                "crs": self._crs,
                "generated_at": None,
                "messages": ["Starting up…"],
                "services": [],
            },
            ensure_ascii=False,
        ).encode("utf-8")

    def _fetch_board(self, view: str) -> DepartureBoard:
        if view == "arrivals":
            return self._service.get_arr_dep_board(self._crs)
        if view == "all":
            return self._service.get_departure_board(
                self._crs, with_details=False, filter_crs=None
            )
        return self._service.get_departure_board(self._crs, with_details=True, **self._bk)

    def get_board(self, view: str) -> DepartureBoard | None:
        """Current board for ``view`` (possibly slightly stale), or None if none fetched yet.

        Never blocks: when the entry is missing or past its TTL, a single background refresh is
        launched (coalesced) and the existing board — if any — is returned meanwhile.
        """
        if view not in VIEWS:
            view = "departures"
        with self._lock:
            entry = self._cache.get(view)
            stale = entry is None or (time.time() - entry[1]) >= self._ttl
            if stale and view not in self._inflight:
                self._inflight.add(view)
                first = not self._started
                self._started = True
                threading.Thread(
                    target=self._refresh, args=(view, first), daemon=True
                ).start()
            return entry[0] if entry else None

    def _refresh(self, view: str, first: bool) -> None:
        """Fetch ``view`` off the request/render thread; keep the last board on failure."""
        if first:
            log.info("First client connected; starting up — querying LDBWS for current state.")
        try:
            board = self._fetch_board(view)
        except LdbwsError as exc:
            log.warning("Fetch of view '%s' failed; keeping last board: %s", view, exc)
            with self._lock:
                self._inflight.discard(view)
            return
        with self._lock:
            self._cache[view] = (board, time.time())
            self._inflight.discard(view)
        log.info("View '%s' refreshed.", view)


def _make_handler(cache: BoardCache) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "RailInfo/0.1"

        def _send(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (stdlib API)
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path == "/board":
                view = parse_qs(parsed.query).get("view", ["departures"])[0]
                if view not in VIEWS:
                    view = "departures"
                board = cache.get_board(view)
                # Always 200: a cold view yields a "starting" board (never a 503), so the
                # simple poll-and-render clients don't have to treat startup as an error.
                self._send(200, _project(view, board) if board is not None else cache.starting)
            elif path == "/healthz":
                self._send(200, json.dumps({"ok": True, "views": list(VIEWS)}).encode("utf-8"))
            else:
                self._send(404, b'{"error":"not found"}')

        do_HEAD = do_GET

        def log_message(self, fmt: str, *args) -> None:
            log.info("%s - %s", self.address_string(), fmt % args)

    return Handler


def make_server(
    cache: BoardCache, *, host: str = "0.0.0.0", port: int = 8000
) -> ThreadingHTTPServer:
    """Build the HTTP server around a (possibly shared) cache, installing no signal handlers.

    The combined ``--serve --pixoo`` mode runs this in a daemon thread and owns signals itself
    (the Pixoo loop's SIGTERM handler); :func:`serve` wraps it for the server-only mode.
    """
    return ThreadingHTTPServer((host, port), _make_handler(cache))


def serve(
    service: BoardService,
    *,
    host: str = "0.0.0.0",
    port: int = 8000,
    interval: float = 30.0,
    crs: str | None = None,
    board_kwargs: dict | None = None,
) -> None:
    """Run the JSON board server (server-only) until interrupted (Ctrl+C) or SIGTERM.

    Returns straight away with an empty cache: no LDBWS call is made until the first client
    connects (see :class:`BoardCache`), so the server can sit idle without burning API quota.
    """
    cache = BoardCache(service, crs=crs, board_kwargs=board_kwargs, ttl=interval)
    httpd = make_server(cache, host=host, port=port)

    def _shutdown(signum: int, _frame: object) -> None:
        log.info("Received signal %d; shutting down.", signum)
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    previous = signal.signal(signal.SIGTERM, _shutdown)
    log.info(
        "Serving departure board on http://%s:%d/board (views: %s) — idle until a client "
        "connects.",
        host, port, ", ".join(VIEWS),
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)
        httpd.server_close()
        log.info("Server stopped.")
