"""Drive the Pixoo: refresh board data periodically while animating the scroll."""

from __future__ import annotations

import time

from railinfo.ldbws.client import LdbwsError
from railinfo.pixoo.device import PixooDevice
from railinfo.renderers.pixoo import render_board_image
from railinfo.service import BoardService

_SCROLL_STEP = 3


def run(
    service: BoardService,
    device: PixooDevice,
    *,
    crs: str | None = None,
    refresh: float = 30.0,
    fps: float = 5.0,
) -> None:
    """Continuously render and push frames until interrupted (Ctrl+C)."""
    frame_interval = 1.0 / fps if fps > 0 else 0.2
    scroll = 0
    board = service.get_departure_board(crs, with_details=True)
    last_refresh = time.monotonic()

    while True:
        now = time.monotonic()
        if now - last_refresh >= refresh:
            try:
                board = service.get_departure_board(crs, with_details=True)
            except LdbwsError:
                pass  # keep showing the last good board until the next refresh
            last_refresh = now

        frame_start = time.monotonic()
        device.push_image(render_board_image(board, scroll=scroll))
        scroll += _SCROLL_STEP
        # The device round-trip caps the rate (~5 fps); only sleep if we beat the budget.
        time.sleep(max(0.0, frame_interval - (time.monotonic() - frame_start)))
