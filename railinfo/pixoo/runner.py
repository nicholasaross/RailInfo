"""Drive the Pixoo: render and push frames from a shared board source, animating the scroll."""

from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from railinfo.domain.models import DepartureBoard
from railinfo.pixoo.device import PixooDevice, PixooError
from railinfo.renderers.pixoo import render_board_image, render_starting_image

_SCROLL_STEP = 3
_PUSH_BACKOFF = 5.0  # seconds to wait after a failed frame push before trying again
_RECONNECT_AFTER = 3  # consecutive push failures before dropping the panel and reconnecting

log = logging.getLogger(__name__)


def run(
    get_board: Callable[[], DepartureBoard | None],
    connect: Callable[[], PixooDevice],
    *,
    fps: float = 5.0,
) -> None:
    """Continuously render and push frames until interrupted or asked to stop.

    ``get_board`` returns the current departures board (or None while the first fetch is still
    in flight). Data fetching and caching are the caller's concern — typically a shared
    :class:`~railinfo.server.BoardCache` — so this loop never calls LDBWS itself, never blocks
    on it, and shares one upstream fetch with the JSON server when they run in one process.

    ``connect`` builds (and readies) a :class:`PixooDevice`, raising :class:`PixooError` if the
    panel can't be reached. The loop **owns the whole device lifecycle**: it connects lazily and
    reconnects via the same ``connect`` after a run of failed pushes, so a Pixoo that is off at
    startup or vanishes mid-stream (powered down, rebooting, off the network) only makes the loop
    back off and retry — it never raises out of ``run``. That independence matters in the merged
    ``--serve --pixoo`` process: the JSON server (the Heltec's data source) runs in a sibling
    thread and **must not** be taken down by an unreachable Pixoo.

    Built to run unattended (e.g. in a container). Stops cleanly on Ctrl+C (SIGINT) or SIGTERM
    (``docker stop``), so cleanup runs and the container exits 0 instead of being killed.
    """
    frame_interval = 1.0 / fps if fps > 0 else 0.2
    scroll = 0
    push_failures = 0
    device: PixooDevice | None = None
    outage_logged = False  # warn once when the panel goes away, then stay quiet until it returns

    with _stop_requested() as should_stop:
        while not should_stop():
            frame_start = time.monotonic()

            if device is None:
                try:
                    device = connect()
                except PixooError as exc:
                    # The panel is off/unreachable. Keep retrying without ever stopping the
                    # process (and, in the merged mode, the JSON server beside us).
                    if not outage_logged:
                        log.warning(
                            "Pixoo unreachable; retrying in the background (the JSON server "
                            "is unaffected): %s", exc,
                        )
                        outage_logged = True
                    else:
                        log.debug("Pixoo still unreachable: %s", exc)
                    _sleep(_PUSH_BACKOFF, should_stop)
                    continue
                log.info("Connected to Pixoo at %s.", device.host)
                outage_logged = False
                push_failures = 0

            board = get_board()
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
                    # Drop the client and reconnect from scratch on the next iteration; a fresh
                    # PixooDevice re-runs Draw/ResetHttpGifId, re-syncing the PicID stream.
                    _safe_close(device)
                    device = None
                    push_failures = 0
                _sleep(_PUSH_BACKOFF, should_stop)
                continue

            push_failures = 0
            scroll += _SCROLL_STEP
            # The device round-trip caps the rate (~5 fps); only sleep if we beat the budget.
            time.sleep(max(0.0, frame_interval - (time.monotonic() - frame_start)))

    if device is not None:
        _safe_close(device)
    log.info("Stopped streaming to Pixoo.")


def _safe_close(device: PixooDevice) -> None:
    """Close a device's socket, ignoring an already-broken connection."""
    try:
        device.close()
    except OSError:
        pass


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
