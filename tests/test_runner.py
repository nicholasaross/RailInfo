"""Tests for the Pixoo run loop's unattended-operation resilience."""

from __future__ import annotations

import signal

import pytest
from conftest import make_service

from railinfo.domain.models import DepartureBoard
from railinfo.pixoo import runner
from railinfo.pixoo.device import PixooError


class _Done(Exception):
    """Sentinel raised from a fake device to break out of the otherwise-infinite loop."""


class _FakeService:
    def __init__(self, board: DepartureBoard) -> None:
        self.board = board

    def get_departure_board(self, crs=None, with_details=False, **kwargs):
        return self.board


class _FlakyDevice:
    """Fails the first two pushes, succeeds on the third, then stops the loop."""

    host = "10.0.0.5"

    def __init__(self) -> None:
        self.pushes = 0

    def push_image(self, image) -> None:
        self.pushes += 1
        if self.pushes <= 2:
            raise PixooError("transient blip")
        if self.pushes == 3:
            return
        raise _Done

    def close(self) -> None:
        pass


def _board() -> DepartureBoard:
    return DepartureBoard(
        location_name="Earlswood",
        crs="ELD",
        generated_at=None,
        services=[make_service(std="13:25", etd="On time")],
    )


def test_run_survives_transient_push_failures(monkeypatch):
    # A dropped frame must not crash the process; the loop backs off and carries on.
    monkeypatch.setattr(runner, "_PUSH_BACKOFF", 0.0)
    device = _FlakyDevice()

    with pytest.raises(_Done):  # the 4th push is our deliberate loop-breaker
        runner.run(_FakeService(_board()), device, crs="ELD", refresh=999, fps=1000)

    assert device.pushes == 4  # 2 failures + 1 success + the sentinel stop


def test_stop_requested_flips_on_sigterm_and_restores_handler():
    before = signal.getsignal(signal.SIGTERM)
    with runner._stop_requested() as should_stop:
        assert should_stop() is False
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)  # simulate delivery
        assert should_stop() is True
    assert signal.getsignal(signal.SIGTERM) is before
