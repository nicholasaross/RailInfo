"""Offline preview of the Pixoo renderer — no live LDBWS call needed.

Builds a representative :class:`DepartureBoard` (on-time / delayed / cancelled services,
plus a long calling-at line) and renders it through ``render_board_image`` exactly as the
device path does, so the thresholded dot-matrix look matches what the panel shows.

Usage (from the repo root)::

    python -m scripts.preview_board                 # writes preview.png (64x64)
    python -m scripts.preview_board --scale 10      # also writes preview@10x.png
    python -m scripts.preview_board -o board.png    # custom output path
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from railinfo.domain.models import CallingPoint, DepartureBoard, Service
from railinfo.renderers.pixoo import render_board_image

SAMPLE = DepartureBoard(
    location_name="London Waterloo",
    crs="WAT",
    generated_at="2026-06-22T17:11:00",
    services=[
        # Top train cancelled — its stops should NOT be the ones shown.
        Service(
            std="17:15", etd=None, sta=None, eta=None, platform="12",
            destination="Reading", destination_crs="RDG", origin=None, via=None,
            operator="SWR", is_cancelled=True,
        ),
        # Delayed (17:18 -> 17:24) and has calling points: this is the row that should be
        # marked with "<" and whose stops scroll below.
        Service(
            std="17:18", etd="17:24", sta=None, eta=None, platform="8",
            destination="Woking", destination_crs="WOK", origin=None, via=None,
            operator="SWR",
            calling_points=[
                CallingPoint("Clapham Junction"),
                CallingPoint("Richmond"),
                CallingPoint("Twickenham"),
                CallingPoint("Woking"),
            ],
        ),
        Service(
            std="17:22", etd="On time", sta=None, eta=None, platform="3",
            destination="Guildford", destination_crs="GLD", origin=None, via=None,
            operator="SWR",
        ),
    ],
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o", "--out", type=Path, default=Path("preview.png"),
        help="Output path for the 64x64 image (default: preview.png).",
    )
    parser.add_argument(
        "--scale", type=int, default=0,
        help="If >1, also save a nearest-neighbour upscale as <name>@<scale>x.png.",
    )
    parser.add_argument(
        "--scroll", type=int, default=0,
        help="Calling-at scroll offset, for previewing a mid-scroll frame.",
    )
    args = parser.parse_args()

    image = render_board_image(SAMPLE, scroll=args.scroll)
    image.save(args.out)
    print(f"Saved {args.out} ({image.width}x{image.height})")

    if args.scale > 1:
        big = image.resize(
            (image.width * args.scale, image.height * args.scale), Image.NEAREST
        )
        big_path = args.out.with_name(f"{args.out.stem}@{args.scale}x{args.out.suffix}")
        big.save(big_path)
        print(f"Saved {big_path} ({big.width}x{big.height})")


if __name__ == "__main__":
    main()
