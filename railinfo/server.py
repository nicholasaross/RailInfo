"""HTTP server exposing the departure board(s) as JSON for LAN display clients.

Three views, selected with ``?view=``:

* ``departures`` (default) — the London-bound board with calling points (the Heltec's
  landscape view, and what the Pixoo shows).
* ``all`` — every departure, no direction filter (the Heltec's portrait view).
* ``arrivals`` — arriving services, labelled by origin (portrait view).

Each view is cached with a short TTL and fetched lazily, so however often a client polls
(the Heltec polls ~5s) it only triggers an upstream LDBWS call when that view's cache is
stale (~once per TTL). A dropped refresh keeps serving the last good payload — the same
keep-serving-stale resilience as :mod:`railinfo.pixoo.runner`. Built from the stdlib only.
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


class ViewCache:
    """Per-view JSON cache, fetched lazily with a TTL and keeping the last good payload."""

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
        self._cache: dict[str, tuple[bytes, float]] = {}

    def _fetch(self, view: str) -> bytes:
        if view == "arrivals":
            board = self._service.get_arr_dep_board(self._crs)
            payload = to_client_dict(board, PORTRAIT_LIMIT, arrivals=True)
        elif view == "all":
            board = self._service.get_departure_board(
                self._crs, with_details=False, filter_crs=None
            )
            payload = to_client_dict(board, PORTRAIT_LIMIT)
        else:  # departures: the filtered, with-calling landscape board
            board = self._service.get_departure_board(
                self._crs, with_details=True, **self._bk
            )
            payload = to_client_dict(board, LANDSCAPE_LIMIT, with_calling=True)
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def get(self, view: str) -> bytes | None:
        if view not in VIEWS:
            view = "departures"
        with self._lock:
            entry = self._cache.get(view)
        if entry and (time.time() - entry[1]) < self._ttl:
            return entry[0]
        try:
            payload = self._fetch(view)
        except LdbwsError as exc:
            log.warning("Fetch of view '%s' failed; serving stale: %s", view, exc)
            return entry[0] if entry else None
        with self._lock:
            self._cache[view] = (payload, time.time())
        log.info("Refreshed view '%s'.", view)
        return payload


def _make_handler(cache: ViewCache) -> type[BaseHTTPRequestHandler]:
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
                payload = cache.get(view)
                if payload is None:
                    self._send(503, b'{"error":"no board yet"}')
                else:
                    self._send(200, payload)
            elif path == "/healthz":
                self._send(200, json.dumps({"ok": True, "views": list(VIEWS)}).encode("utf-8"))
            else:
                self._send(404, b'{"error":"not found"}')

        do_HEAD = do_GET

        def log_message(self, fmt: str, *args) -> None:
            log.info("%s - %s", self.address_string(), fmt % args)

    return Handler


def serve(
    service: BoardService,
    *,
    host: str = "0.0.0.0",
    port: int = 8000,
    interval: float = 30.0,
    crs: str | None = None,
    board_kwargs: dict | None = None,
) -> None:
    """Run the JSON board server until interrupted (Ctrl+C) or SIGTERM (``docker stop``)."""
    cache = ViewCache(service, crs=crs, board_kwargs=board_kwargs, ttl=interval)
    cache.get("departures")  # prime the default view so the first request is ready

    httpd = ThreadingHTTPServer((host, port), _make_handler(cache))

    def _shutdown(signum: int, _frame: object) -> None:
        log.info("Received signal %d; shutting down.", signum)
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    previous = signal.signal(signal.SIGTERM, _shutdown)
    log.info(
        "Serving departure board on http://%s:%d/board (views: %s)",
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
