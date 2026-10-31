"""Tests for railinfo.service — the directional-filter resolution in particular."""

from __future__ import annotations

from typing import Any

from railinfo.config import Endpoint, Settings
from railinfo.service import BoardService


class RecordingClient:
    """A fake LdbwsClient that records get_board kwargs and returns an empty board."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_board(self, endpoint, crs, **kwargs) -> dict[str, Any]:
        self.calls.append({"crs": crs, **kwargs})
        return {"locationName": "Earlswood (Surrey)", "crs": crs, "trainServices": []}


class DirectionalClient:
    """A fake LdbwsClient whose board depends on the direction filter (records each call)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_board(self, endpoint, crs, **kwargs) -> dict[str, Any]:
        self.calls.append({"crs": crs, **kwargs})
        if not kwargs.get("filter_crs"):
            dests = ["Horsham", "Peterborough"]  # unfiltered: both directions
        elif kwargs.get("filter_type") == "to":
            dests = ["Peterborough"]  # calls at the filter CRS next
        else:
            dests = ["Horsham"]  # came via the filter CRS
        services = [
            {"std": "11:12", "etd": "On time", "serviceID": d, "destination": [{"locationName": d}]}
            for d in dests
        ]
        return {"locationName": "Earlswood (Surrey)", "crs": crs, "trainServices": services}


def _settings(**overrides) -> Settings:
    base = dict(
        endpoints={"ldb": Endpoint(name="ldb", url_template="http://x/{crs}", api_key="k")},
        station_crs="ELD",
        direction_filter_crs="LBG",
        direction_filter_type="to",
    )
    base.update(overrides)
    return Settings(**base)


def test_default_applies_configured_direction_filter():
    client = RecordingClient()
    BoardService(_settings(), client=client).get_departure_board()
    call = client.calls[-1]
    assert call["filter_crs"] == "LBG"
    assert call["filter_type"] == "to"


def test_explicit_none_forces_no_filter():
    client = RecordingClient()
    BoardService(_settings(), client=client).get_departure_board(filter_crs=None)
    assert client.calls[-1]["filter_crs"] is None


def test_explicit_override_takes_precedence():
    client = RecordingClient()
    BoardService(_settings(), client=client).get_departure_board(
        filter_crs="VIC", filter_type="from"
    )
    call = client.calls[-1]
    assert call["filter_crs"] == "VIC"
    assert call["filter_type"] == "from"


def test_no_configured_default_means_no_filter():
    client = RecordingClient()
    BoardService(_settings(direction_filter_crs=None), client=client).get_departure_board()
    assert client.calls[-1]["filter_crs"] is None


def test_crs_falls_back_to_station_when_unspecified():
    client = RecordingClient()
    BoardService(_settings(), client=client).get_departure_board()
    assert client.calls[-1]["crs"] == "ELD"


def test_split_board_uses_opposite_filters_for_the_two_halves():
    client = DirectionalClient()
    split = BoardService(_settings(direction_filter_crs="RDH"), client=client).get_split_board()
    assert [(c["filter_crs"], c["filter_type"]) for c in client.calls] == [
        ("RDH", "to"),
        ("RDH", "from"),
    ]
    assert [s.destination for s in split.northbound] == ["Peterborough"]
    assert [s.destination for s in split.southbound] == ["Horsham"]
    assert split.board.location_name == "Earlswood (Surrey)"


def test_split_board_flips_a_configured_from_filter():
    client = DirectionalClient()
    settings = _settings(direction_filter_crs="RDH", direction_filter_type="from")
    BoardService(settings, client=client).get_split_board()
    assert [c["filter_type"] for c in client.calls] == ["from", "to"]


def test_split_board_without_a_direction_filter_is_all_northbound():
    client = DirectionalClient()
    split = BoardService(_settings(direction_filter_crs=None), client=client).get_split_board()
    assert len(client.calls) == 1 and client.calls[0]["filter_crs"] is None  # nothing to split on
    assert [s.destination for s in split.northbound] == ["Horsham", "Peterborough"]
    assert split.southbound == []
