"""CLI entry point: fetch a live board and render it to the terminal."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from railinfo.config import ConfigError, load_settings
from railinfo.ldbws.client import LdbwsError
from railinfo.renderers import terminal
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

    try:
        if args.next:
            board = service.get_next_departures(args.crs, filter_list)
        elif args.arrdep:
            board = service.get_arr_dep_board(args.crs)
        else:
            board = service.get_departure_board(args.crs, with_details=args.details)
    except (LdbwsError, ConfigError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(dataclasses.asdict(board), indent=2, ensure_ascii=False))
    else:
        terminal.render(board)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
