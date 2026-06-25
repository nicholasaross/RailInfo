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
    board = _board()

    with pytest.raises(_Done):  # the 4th push is our deliberate loop-breaker
        runner.run(lambda: board, lambda: device, fps=1000)

    assert device.pushes == 4  # 2 failures + 1 success + the sentinel stop


class _OneShotDevice:
    """Pushes one frame successfully, then stops the loop on the next push."""

    host = "10.0.0.9"

    def __init__(self) -> None:
        self.pushes = 0

    def push_image(self, image) -> None:
        self.pushes += 1
        if self.pushes >= 2:
            raise _Done

    def close(self) -> None:
        pass


def test_run_survives_pixoo_unreachable_at_startup(monkeypatch):
    # The crux of the decoupling: a Pixoo that's off when the loop starts must not crash the
    # process (which, in the merged mode, would take the JSON server down). The loop retries the
    # connector until the panel answers, then streams — it never raises out of run().
    monkeypatch.setattr(runner, "_PUSH_BACKOFF", 0.0)
    board = _board()
    device = _OneShotDevice()
    attempts = {"n": 0}

    def connect():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise PixooError("[Errno 113] No route to host")
        return device

    with pytest.raises(_Done):
        runner.run(lambda: board, connect, fps=1000)

    assert attempts["n"] == 3  # two failed connects, third succeeds
    assert device.pushes == 2  # then it streamed (one frame + the sentinel stop)


def test_run_reconnects_via_connector_after_repeated_failures(monkeypatch):
    # After _RECONNECT_AFTER consecutive push failures the loop drops the panel (closing it) and
    # rebuilds a fresh device from the connector — re-syncing the Pixoo PicID stream.
    monkeypatch.setattr(runner, "_PUSH_BACKOFF", 0.0)
    monkeypatch.setattr(runner, "_RECONNECT_AFTER", 2)
    board = _board()

    class _Failer:
        host = "10.0.0.7"

        def __init__(self) -> None:
            self.pushes = 0
            self.closed = False

        def push_image(self, image) -> None:
            self.pushes += 1
            raise PixooError("blip")

        def close(self) -> None:
            self.closed = True

    class _Stopper:
        host = "10.0.0.8"

        def push_image(self, image) -> None:
            raise _Done

        def close(self) -> None:
            pass

    first, second = _Failer(), _Stopper()
    handed = iter([first, second])

    with pytest.raises(_Done):
        runner.run(lambda: board, lambda: next(handed), fps=1000)

    assert first.pushes == 2  # failed twice, then was dropped
    assert first.closed is True  # cleaned up on drop before reconnecting


def test_stop_requested_flips_on_sigterm_and_restores_handler():
    before = signal.getsignal(signal.SIGTERM)
    with runner._stop_requested() as should_stop:
        assert should_stop() is False
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)  # simulate delivery
        assert should_stop() is True
    assert signal.getsignal(signal.SIGTERM) is before
