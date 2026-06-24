"""Drive the Pixoo: render and push frames from a shared board source, animating the scroll."""

from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from railinfo.domain.models import DepartureBoard
from railinfo.pixoo.device import PixooDevice, PixooError, discover_host
from railinfo.renderers.pixoo import render_board_image, render_starting_image

_SCROLL_STEP = 3
_PUSH_BACKOFF = 5.0  # seconds to wait after a failed frame push before trying again
_RECONNECT_AFTER = 3  # consecutive push failures before re-discovering the panel

log = logging.getLogger(__name__)


def run(
    get_board: Callable[[], DepartureBoard | None],
    device: PixooDevice,
    *,
    fps: float = 5.0,
) -> None:
    """Continuously render and push frames until interrupted or asked to stop.

    ``get_board`` returns the current departures board (or None while the first fetch is still
    in flight). Data fetching and caching are the caller's concern — typically a shared
    :class:`~railinfo.server.BoardCache` — so this loop never calls LDBWS itself, never blocks
    on it, and shares one upstream fetch with the JSON server when they run in one process.

    Built to run unattended (e.g. in a container): a failed frame push backs off and eventually
    re-discovers the panel rather than crashing. Stops cleanly on Ctrl+C (SIGINT) or SIGTERM
    (``docker stop``), so cleanup runs and the container exits 0 instead of being killed.
    """
    frame_interval = 1.0 / fps if fps > 0 else 0.2
    scroll = 0
    push_failures = 0

    with _stop_requested() as should_stop:
        while not should_stop():
            board = get_board()
            frame_start = time.monotonic()
            image = (
                render_board_image(board, scroll=scroll)
                if board is not None
                else render_starting_image()
            )
            try:
                device.push_image(image)
            except PixooError as exc:
                push_failures += 1
                log.warning(
                    "Frame push to %s failed (attempt %d): %s",
                    device.host, push_failures, exc,
                )
                if push_failures >= _RECONNECT_AFTER:
                    device = _reconnect(device) or device
                    push_failures = 0
                _sleep(_PUSH_BACKOFF, should_stop)
                continue

            push_failures = 0
            scroll += _SCROLL_STEP
            # The device round-trip caps the rate (~5 fps); only sleep if we beat the budget.
            time.sleep(max(0.0, frame_interval - (time.monotonic() - frame_start)))

    log.info("Stopped streaming to Pixoo.")


def _reconnect(device: PixooDevice) -> PixooDevice | None:
    """Best-effort recovery: drop the old client and build a fresh one.

    Re-runs LAN discovery in case DHCP moved the panel, falling back to the known host.
    Returns the new device, or None if it still can't be reached (caller keeps the old one
    and keeps retrying).
    """
    try:
        device.close()
    except OSError:
        pass
    host = discover_host() or device.host
    try:
        reconnected = PixooDevice(host)
    except PixooError as exc:
        log.warning("Reconnect to %s failed: %s", host, exc)
        return None
    log.info("Reconnected to Pixoo at %s", host)
    return reconnected


@contextmanager
def _stop_requested() -> Iterator[Callable[[], bool]]:
    """Yield a predicate that becomes True when SIGTERM arrives, restoring the prior handler.

    Only SIGTERM is intercepted; SIGINT keeps raising KeyboardInterrupt so an interactive
    Ctrl+C unwinds as before. Signal handlers must be set from the main thread.
    """
    stop = False

    def handler(signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True
        log.info("Received signal %d; stopping after the current frame.", signum)

    previous = signal.signal(signal.SIGTERM, handler)
    try:
        yield lambda: stop
    finally:
        signal.signal(signal.SIGTERM, previous)


def _sleep(duration: float, should_stop: Callable[[], bool]) -> None:
    """Sleep up to ``duration`` seconds, waking early if a stop is requested."""
    end = time.monotonic() + duration
    while not should_stop():
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.2, remaining))
