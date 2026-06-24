"""Tests for the Phase 4 JSON server: projection, per-view caching, and HTTP serving."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from conftest import make_service

from railinfo.domain.models import CallingPoint, DepartureBoard
from railinfo.ldbws.client import LdbwsError
from railinfo.server import ViewCache, _make_handler, _stops_index, to_client_dict


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


class _FailingService:
    def get_departure_board(self, crs=None, with_details=False, **kwargs):
        raise LdbwsError("upstream down")

    def get_arr_dep_board(self, crs=None):
        raise LdbwsError("upstream down")


def test_stops_index_skips_cancelled():
    assert _stops_index(_dep_board().services) == 1  # index 0 is cancelled despite stops


def test_to_client_dict_departures_with_calling():
    data = to_client_dict(_dep_board(), limit=2, with_calling=True)
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


def test_cache_lazy_then_ttl_then_keep_stale():
    svc = _FakeService()
    cache = ViewCache(svc, ttl=999)
    p1 = cache.get("departures")
    assert p1 is not None and svc.dep_calls == 1
    cache.get("departures")  # within TTL -> served from cache, no new fetch
    assert svc.dep_calls == 1

    cache._ttl = 0  # force staleness; failing service must keep the last good payload
    cache._service = _FailingService()
    assert cache.get("departures") == p1


def test_cache_views_are_independent():
    svc = _FakeService()
    cache = ViewCache(svc, ttl=999)
    cache.get("all")
    cache.get("arrivals")
    assert svc.dep_calls == 1 and svc.arr_calls == 1
    arr = json.loads(cache.get("arrivals"))
    assert arr["services"][0]["destination"] == "London Bridge"  # origin


def _serve(cache):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(cache))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def test_http_serves_views_and_health():
    httpd = _serve(ViewCache(_FakeService(), ttl=999))
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


def test_http_503_before_first_board():
    httpd = _serve(ViewCache(_FailingService(), ttl=999))
    port = httpd.server_address[1]
    try:
        code = None
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/board", timeout=5)
        except urllib.error.HTTPError as exc:
            code = exc.code
        assert code == 503
    finally:
        httpd.shutdown()
        httpd.server_close()
