"""Tests for railinfo.domain.mapper — LDBWS JSON → domain model."""

from __future__ import annotations

from railinfo.domain.mapper import from_ldbws, from_service_details

# A GetDepartureBoard-style payload (services under "trainServices").
STATION_BOARD = {
    "locationName": "Earlswood (Surrey)",
    "crs": "ELD",
    "generatedAt": "2026-06-22T13:00:00",
    "nrccMessages": [{"Value": "<p>Delays <b>are</b> expected</p>"}],
    "trainServices": [
        {
            "std": "13:25",
            "etd": "13:28",
            "platform": "1",
            "operator": "Thameslink",
            "serviceID": "svc-1",
            "isCancelled": False,
            "destination": [
                {"locationName": "Peterborough", "crs": "PBO", "via": "via London Bridge"}
            ],
            "origin": [{"locationName": "Horsham", "crs": "HRH"}],
            "subsequentCallingPoints": [
                {
                    "callingPoint": [
                        {"locationName": "Redhill", "crs": "RDH", "st": "13:29", "et": "13:32"},
                        {"locationName": "London Bridge", "crs": "LBG", "st": "14:00", "et": "On time"},
                    ]
                }
            ],
        }
    ],
}

# A GetNextDepartures-style payload (services under "departures[].service").
DEPARTURES_BOARD = {
    "locationName": "Earlswood (Surrey)",
    "crs": "ELD",
    "departures": [
        {"crs": "LBG", "service": {"std": "13:25", "etd": "On time", "destination": [{"locationName": "Peterborough", "crs": "PBO"}]}},
        {"crs": "VIC", "service": None},  # filtered destination with no train → skipped
    ],
}


def test_none_payload_yields_empty_board():
    board = from_ldbws(None)
    assert board.services == []
    assert board.location_name is None


def test_station_board_maps_core_fields():
    board = from_ldbws(STATION_BOARD)
    assert board.location_name == "Earlswood (Surrey)"
    assert board.crs == "ELD"
    assert len(board.services) == 1

    svc = board.services[0]
    assert svc.std == "13:25"
    assert svc.etd == "13:28"
    assert svc.destination == "Peterborough"
    assert svc.destination_crs == "PBO"
    assert svc.via == "via London Bridge"
    assert svc.origin == "Horsham"
    assert svc.service_id == "svc-1"
    assert not svc.is_cancelled


def test_station_board_maps_calling_points():
    svc = from_ldbws(STATION_BOARD).services[0]
    assert [cp.location for cp in svc.calling_points] == ["Redhill", "London Bridge"]
    assert svc.calling_points[0].et == "13:32"


def test_nrcc_messages_strip_html():
    board = from_ldbws(STATION_BOARD)
    assert board.nrcc_messages == ["Delays are expected"]


def test_departures_board_shape_and_skips_missing_service():
    board = from_ldbws(DEPARTURES_BOARD)
    assert len(board.services) == 1  # the None service is dropped
    assert board.services[0].destination_crs == "PBO"


def test_multiple_destinations_join_with_ampersand():
    payload = {
        "trainServices": [
            {
                "destination": [
                    {"locationName": "Portsmouth", "crs": "PMS"},
                    {"locationName": "Bognor Regis", "crs": "BOG"},
                ]
            }
        ]
    }
    svc = from_ldbws(payload).services[0]
    assert svc.destination == "Portsmouth & Bognor Regis"
    assert svc.destination_crs == "PMS & BOG"


def test_service_details_derives_destination_and_origin():
    payload = {
        "std": "13:25",
        "etd": "On time",
        "operator": "Thameslink",
        "previousCallingPoints": [
            {"callingPoint": [{"locationName": "Horsham", "crs": "HRH"}]}
        ],
        "subsequentCallingPoints": [
            {
                "callingPoint": [
                    {"locationName": "Redhill", "crs": "RDH"},
                    {"locationName": "Peterborough", "crs": "PBO"},
                ]
            }
        ],
    }
    svc = from_service_details(payload)
    assert svc.destination == "Peterborough"  # last subsequent calling point
    assert svc.destination_crs == "PBO"
    assert svc.origin == "Horsham"  # first previous calling point
