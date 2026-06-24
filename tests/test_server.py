"""Tests for the Phase 4 JSON server: projection, the shared board cache, and HTTP serving."""

from __future__ import annotations

import json
import threading
import time
import urllib.request

from conftest import make_service

from railinfo.domain.models import CallingPoint, DepartureBoard
from railinfo.ldbws.client import LdbwsError
from railinfo.server import BoardCache, _project, _stops_index, make_server, to_client_dict


def _ready(cache: BoardCache, view: str = "departures") -> DepartureBoard:
    """Touch a view and drive its background fetch to completion, returning the board.

    The first ``get_board`` returns None and kicks off the fetch on a thread; poll until the
    board lands.
    """
    for _ in range(200):
        board = cache.get_board(view)
        if board is not None:
            return board
        time.sleep(0.005)
    raise AssertionError("view never became ready: " + view)


def _settle(cache: BoardCache, view: str = "departures") -> None:
    """Wait until no fetch is in flight for a view (e.g. after a failing refresh)."""
    for _ in range(200):
        if view not in cache._inflight:
            return
        time.sleep(0.005)


def _dep_board() -> DepartureBoard:
    return DepartureBoard(
        location_name="Earlswood",
        crs="ELD",
        generated_at="2026-06-23T14:05:00",
        nrcc_messages=["Reduced service today."],
        services=[
            make_service(  # cancelled but has stops -> not the chosen "calling at" service
                std="14:10", etd=None, destination="Reading", destination_crs="RDG",
                is_cancelled=True, calling_points=[CallingPoint("Redhill")],
            ),
            make_service(
                std="14:12", etd="On time", destination="London Bridge",
                destination_crs="LBG", platform="2",
                calling_points=[CallingPoint("Redhill"), CallingPoint("East Croydon")],
            ),
            make_service(std="14:18", etd="14:24", destination="Victoria", destination_crs="VIC"),
        ],
    )


def _arr_board() -> DepartureBoard:
    return DepartureBoard(
        location_name="Earlswood", crs="ELD", generated_at="2026-06-23T14:05:00",
        services=[
            make_service(std=None, etd=None, sta="14:09", eta="14:15",
                         origin="London Bridge", destination="Three Bridges", platform="1"),
        ],
    )


class _FakeService:
    def __init__(self) -> None:
        self.dep_calls = 0
        self.arr_calls = 0

    def get_departure_board(self, crs=None, with_details=False, **kwargs) -> DepartureBoard:
        self.dep_calls += 1
        return _dep_board()

    def get_arr_dep_board(self, crs=None) -> DepartureBoard:
        self.arr_calls += 1
        return _arr_board()


class _SlowService(_FakeService):
    def get_departure_board(self, crs=None, with_details=False, **kwargs) -> DepartureBoard:
        time.sleep(0.1)  # hold the fetch open so concurrent reads overlap a single call
        return super().get_departure_board(crs, with_details, **kwargs)


class _FailingService:
    def get_departure_board(self, crs=None, with_details=False, **kwargs):
        raise LdbwsError("upstream down")

    def get_arr_dep_board(self, crs=None):
        raise LdbwsError("upstream down")


def test_stops_index_skips_cancelled():
    assert _stops_index(_dep_board().services) == 1  # index 0 is cancelled despite stops


def test_to_client_dict_departures_with_calling():
    data = to_client_dict(_dep_board(), limit=2, with_calling=True)
    assert data["status"] == "ready"
    assert data["station"] == "Earlswood"
    assert len(data["services"]) == 2
    assert data["stops_index"] == 1
    assert data["calling_at"] == ["Redhill", "East Croydon"]
    top = data["services"][1]
    assert top["time"] == "14:12"
    assert top["destination"] == "London Bridge"
    assert top["platform"] == "2"


def test_to_client_dict_arrivals_uses_origin_and_arrival_time():
    data = to_client_dict(_arr_board(), arrivals=True)
    svc = data["services"][0]
    assert svc["time"] == "14:09"          # scheduled arrival
    assert svc["expected"] == "14:15"       # expected arrival
    assert svc["destination"] == "London Bridge"  # origin shown as the label
    assert "calling_at" not in data         # portrait views omit calling points


def test_project_selects_view_shape():
    assert "calling_at" in json.loads(_project("departures", _dep_board()))  # landscape
    assert "calling_at" not in json.loads(_project("all", _dep_board()))     # portrait list


def test_cache_starts_lazily_then_serves_board():
    svc = _FakeService()
    cache = BoardCache(svc, ttl=999)
    assert cache.get_board("departures") is None  # lazy: kicks off the fetch, no board yet
    board = _ready(cache, "departures")           # background fetch lands
    assert board.location_name == "Earlswood" and svc.dep_calls == 1
    cache.get_board("departures")  # within TTL -> served from cache, no new fetch
    assert svc.dep_calls == 1


def test_cache_keeps_last_board_on_failure():
    svc = _FakeService()
    cache = BoardCache(svc, ttl=999)
    good = _ready(cache, "departures")
    cache._ttl = 0  # force staleness
    cache._service = _FailingService()  # the next refresh fails
    assert cache.get_board("departures") is good  # stale board served while a refresh runs
    _settle(cache, "departures")  # the background refresh fails and clears inflight
    assert cache.get_board("departures") is good  # last good board retained


def test_cache_coalesces_concurrent_stale_reads():
    # Many rapid reads while one fetch is in flight must trigger only ONE upstream call -- this
    # is what lets the ~5 fps Pixoo poll share the server's fetch instead of multiplying it.
    svc = _SlowService()
    cache = BoardCache(svc, ttl=999)
    for _ in range(10):
        assert cache.get_board("departures") is None  # all land during the single fetch
        time.sleep(0.002)  # 10 x 2ms << the 100ms fetch, so they overlap it
    _ready(cache, "departures")
    assert svc.dep_calls == 1


def test_cache_views_are_independent():
    svc = _FakeService()
    cache = BoardCache(svc, ttl=999)
    _ready(cache, "all")
    arr = _ready(cache, "arrivals")
    assert svc.dep_calls == 1 and svc.arr_calls == 1
    data = json.loads(_project("arrivals", arr))
    assert data["services"][0]["destination"] == "London Bridge"  # origin shown as the label


def _serve(cache):
    httpd = make_server(cache, host="127.0.0.1", port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def test_http_serves_views_and_health():
    cache = BoardCache(_FakeService(), ttl=999)
    _ready(cache, "departures")  # drive the lazy initial fetches before hitting the API
    _ready(cache, "arrivals")
    httpd = _serve(cache)
    port = httpd.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/board", timeout=5) as r:
            assert json.loads(r.read())["calling_at"] == ["Redhill", "East Croydon"]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/board?view=arrivals", timeout=5) as r:
            assert json.loads(r.read())["services"][0]["time"] == "14:09"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as r:
            assert json.loads(r.read())["ok"] is True
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_starting_before_first_board():
    # A cold view answers 200 with a "starting" board (not a 503), so the poll-and-render
    # clients treat startup as a normal frame. A failing upstream just keeps it "starting".
    httpd = _serve(BoardCache(_FailingService(), ttl=999))
    port = httpd.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/board", timeout=5) as r:
            data = json.loads(r.read())
        assert data["status"] == "starting"
        assert data["services"] == []
    finally:
        httpd.shutdown()
        httpd.server_close()
