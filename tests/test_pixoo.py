"""Tests for the Pixoo renderer's pure logic and a render smoke test."""

from __future__ import annotations

from conftest import make_service

from railinfo.domain.models import CallingPoint, DepartureBoard
from railinfo.renderers import pixoo
from railinfo.renderers.pixoo import (
    AMBER,
    ORANGE,
    RED,
    SIZE,
    _choose_stops_index,
    _headline_time,
    _status_colour,
    render_board_image,
)


# --- _headline_time: delayed shows revised time, otherwise scheduled ---------------

def test_headline_time_on_time_shows_scheduled():
    assert _headline_time(make_service(std="13:25", etd="On time")) == "13:25"


def test_headline_time_delayed_shows_revised():
    assert _headline_time(make_service(std="13:25", etd="13:28")) == "13:28"


def test_headline_time_cancelled_shows_scheduled():
    svc = make_service(std="13:25", etd=None, is_cancelled=True)
    assert _headline_time(svc) == "13:25"


def test_headline_time_delayed_without_specific_time_falls_back():
    # "Delayed" has no colon, so we keep the scheduled time (still coloured orange).
    assert _headline_time(make_service(std="13:25", etd="Delayed")) == "13:25"


# --- _status_colour ----------------------------------------------------------------

def test_status_colour_mapping():
    assert _status_colour(make_service(etd="On time")) == AMBER
    assert _status_colour(make_service(etd="13:28")) == ORANGE
    assert _status_colour(make_service(is_cancelled=True)) == RED


# --- _choose_stops_index -----------------------------------------------------------

def _with_stops():
    return make_service(calling_points=[CallingPoint("Redhill")])


def test_choose_stops_prefers_first_with_calling_points():
    services = [_with_stops(), _with_stops()]
    assert _choose_stops_index(services) == 0


def test_choose_stops_skips_cancelled_top_train():
    cancelled = make_service(is_cancelled=True, calling_points=[CallingPoint("Redhill")])
    services = [cancelled, _with_stops()]
    assert _choose_stops_index(services) == 1


def test_choose_stops_skips_services_without_calling_points():
    services = [make_service(calling_points=[]), _with_stops()]
    assert _choose_stops_index(services) == 1


def test_choose_stops_returns_none_when_nothing_qualifies():
    assert _choose_stops_index([make_service(calling_points=[])]) is None
    assert _choose_stops_index([]) is None


# --- render_board_image smoke test: valid frame, fully thresholded -----------------

def test_render_produces_thresholded_64x64_frame():
    board = DepartureBoard(
        location_name="Earlswood (Surrey)",
        crs="ELD",
        generated_at=None,
        services=[
            make_service(is_cancelled=True),
            make_service(std="13:25", etd="13:28", calling_points=[CallingPoint("Redhill")]),
        ],
    )
    image = render_board_image(board, scroll=0)
    assert image.size == (SIZE, SIZE)
    assert image.mode == "RGB"
    # Thresholding leaves no partial-brightness fringe: every pixel is black or >= cutoff.
    px = image.load()
    for y in range(SIZE):
        for x in range(SIZE):
            peak = max(px[x, y])
            assert peak == 0 or peak >= pixoo._THRESHOLD
