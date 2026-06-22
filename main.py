"""CLI entry point: fetch a live board and render it to the terminal."""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys

from railinfo.config import ConfigError, Settings, load_settings
from railinfo.ldbws.client import LdbwsError
from railinfo.pixoo.device import PixooDevice, PixooError, discover_host
from railinfo.pixoo.runner import run as run_pixoo
from railinfo.renderers import terminal
from railinfo.renderers.pixoo import render_board_image
from railinfo.service import BoardService


def main() -> int:
    # The legacy Windows console defaults to cp1252; switch to UTF-8 so station names
    # and messages with non-cp1252 characters render instead of crashing.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description="Live National Rail departure board (LDBWS)."
    )
    parser.add_argument("--crs", help="Station CRS code (defaults to STATION_CRS in .env).")
    parser.add_argument(
        "--filter",
        help="Comma-separated destination CRS codes (used with --next).",
    )
    direction = parser.add_mutually_exclusive_group()
    direction.add_argument(
        "--to",
        metavar="CRS",
        help="Only services that call at this station (e.g. LBG for London-bound). "
        "Overrides DIRECTION_FILTER_CRS in .env.",
    )
    direction.add_argument(
        "--from",
        dest="from_crs",
        metavar="CRS",
        help="Only services that called at this station before here.",
    )
    direction.add_argument(
        "--all-directions",
        action="store_true",
        help="Ignore the DIRECTION_FILTER_CRS default and show every direction.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--next",
        action="store_true",
        help="Use the Live Next Departures Board (next train to each filtered destination).",
    )
    source.add_argument(
        "--arrdep",
        action="store_true",
        help="Use the Live Arrival and Departure Boards (with calling points).",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Enrich the departure board with calling points via Service Details "
        "(one extra request per service).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the normalised domain model as JSON instead of rendering.",
    )
    pixoo = parser.add_argument_group("Pixoo 64 (Phase 2)")
    pixoo.add_argument(
        "--pixoo", action="store_true", help="Render the departure board to the Pixoo 64."
    )
    pixoo.add_argument(
        "--loop",
        action="store_true",
        help="With --pixoo: keep refreshing and scrolling until interrupted.",
    )
    pixoo.add_argument(
        "--interval", type=float, default=30.0, help="Data refresh seconds in --loop."
    )
    pixoo.add_argument("--fps", type=float, default=5.0, help="Scroll frame rate in --loop.")
    pixoo.add_argument(
        "--pixoo-host", help="Pixoo IP (else PIXOO_HOST in .env, else auto-discover)."
    )
    pixoo.add_argument("--brightness", type=int, help="Set Pixoo brightness (0-100).")
    pixoo.add_argument(
        "--preview", metavar="PATH", help="Save a 64x64 PNG preview instead of pushing."
    )
    args = parser.parse_args()

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    service = BoardService(settings)
    filter_list = (
        [c.strip() for c in args.filter.split(",") if c.strip()] if args.filter else None
    )
    direction = _direction_kwargs(args)

    if args.pixoo or args.preview:
        return _run_pixoo(args, settings, service, direction)

    try:
        if args.next:
            board = service.get_next_departures(args.crs, filter_list)
        elif args.arrdep:
            board = service.get_arr_dep_board(args.crs)
        else:
            board = service.get_departure_board(
                args.crs, with_details=args.details, **direction
            )
    except (LdbwsError, ConfigError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(dataclasses.asdict(board), indent=2, ensure_ascii=False))
    else:
        terminal.render(board)
    return 0


def _direction_kwargs(args) -> dict[str, object]:
    """Translate --to/--from/--all-directions into get_departure_board kwargs.

    Returns an empty dict when none is given, so the configured DIRECTION_FILTER_CRS
    default applies.
    """
    if args.all_directions:
        return {"filter_crs": None}  # explicit override: no filter
    if args.to:
        return {"filter_crs": args.to, "filter_type": "to"}
    if args.from_crs:
        return {"filter_crs": args.from_crs, "filter_type": "from"}
    return {}


def _run_pixoo(
    args, settings: Settings, service: BoardService, direction: dict[str, object]
) -> int:
    try:
        board = service.get_departure_board(args.crs, with_details=True, **direction)
    except (LdbwsError, ConfigError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.preview:
        render_board_image(board).save(args.preview)
        print(f"Saved preview to {args.preview}")
        return 0

    host = args.pixoo_host or settings.pixoo_host or discover_host()
    if not host:
        print(
            "Could not find a Pixoo on the network. Set PIXOO_HOST in .env or pass "
            "--pixoo-host.",
            file=sys.stderr,
        )
        return 1

    try:
        device = PixooDevice(host)
        if args.brightness is not None:
            device.set_brightness(args.brightness)
        if args.loop:
            # Unattended/long-running: send the runner's progress and warnings to stdout
            # so they're visible via `docker logs` (and the terminal when run directly).
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            )
            # httpx logs every request ("HTTP Request: ...") at INFO; at ~5 fps that floods
            # the log, so keep it (and httpcore) to warnings only.
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("httpcore").setLevel(logging.WARNING)
            print(f"Streaming to Pixoo at {host} (Ctrl+C to stop)...")
            run_pixoo(
                service,
                device,
                crs=args.crs,
                refresh=args.interval,
                fps=args.fps,
                board_kwargs=direction,
            )
        else:
            device.push_image(render_board_image(board))
            print(f"Pushed departure board to Pixoo at {host}.")
    except KeyboardInterrupt:
        print("\nStopped.")
    except PixooError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
