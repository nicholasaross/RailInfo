"""Render a :class:`~railinfo.domain.models.DepartureBoard` to a 64x64 image.

National-Rail dot-matrix look: amber text on black. Layout (64x64):

* rows 0-2  — up to three departures: ``CRS  HH:MM`` (destination code + time, colour =
  status). Codes keep names short so the font stays large and legible. A delayed service
  shows its revised expected time, not the scheduled one.
* row ~35   — the "calling at …" line for the first *non-cancelled* departure, scrolled
  horizontally. If that isn't the top row, a ``<`` after its code marks which train it is.
* rows 47+  — a large centred clock.

``scroll`` is a pixel offset advanced by the run loop to animate the calling-at line; at
``scroll=0`` the image is a valid static frame (used for one-shot pushes and previews).
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from railinfo.domain.models import DepartureBoard, Service

SIZE = 64
_FONT_PATH = Path(__file__).resolve().parents[2] / "Fonts" / "national-rail-dmi-regular.ttf"

BLACK = (0, 0, 0)
AMBER = (255, 176, 0)
ORANGE = (255, 110, 0)
RED = (255, 45, 35)

# One body size for everything (codes/times/calling) — it lands on whole pixels so the
# dot-matrix font thresholds crisply (see _threshold). The clock is doubled for emphasis.
_BODY_FONT = 9
_CODE_FONT = _BODY_FONT
_TIME_FONT = _BODY_FONT
_CALLING_FONT = _BODY_FONT
_CLOCK_FONT = _BODY_FONT * 2
_ROW_PITCH = 11  # codes/digits have no descenders, so rows can sit tight
_MARGIN = 2  # keep text off the very edge
_CALLING_Y = 35
_CLOCK_Y = 46  # 18px-tall clock would clip the bottom row at 47
_STRIP_H = 9
# Pixels dimmer than this (in their brightest channel) are antialiasing fringe → snapped
# to black; the rest keep full colour. Removes the halos a TTF outline leaves at this size.
_THRESHOLD = 96

# Shorten common long tokens so truncation keeps meaning (order matters).
_ABBREVIATIONS = {
    "London ": "Ldn ",
    " International": " Intl",
    " Airport": " Apt",
    " Parkway": " Pkwy",
    " Junction": " Jn",
    " Central": " Ctl",
    " Street": " St",
}


@lru_cache(maxsize=4)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONT_PATH), size)


def _status_colour(service: Service) -> tuple[int, int, int]:
    if service.is_cancelled:
        return RED
    if service.expected == "On time":
        return AMBER
    return ORANGE


def render_board_image(board: DepartureBoard, *, scroll: int = 0, now: datetime | None = None) -> Image.Image:
    image = Image.new("RGB", (SIZE, SIZE), BLACK)
    draw = ImageDraw.Draw(image)

    services = board.services[:3]
    if not services:
        draw.text((0, 0), "No departures", font=_font(_TIME_FONT), fill=AMBER)

    stops_index = _choose_stops_index(services)
    for index, service in enumerate(services):
        # Mark the row whose stops are shown, unless it's the top row (the default).
        _draw_departure(
            draw, service, y=index * _ROW_PITCH, mark=index == stops_index and index > 0
        )

    if stops_index is not None:
        stops = ", ".join(cp.location for cp in services[stops_index].calling_points)
        calling = _font(_CALLING_FONT)
        _draw_scrolling(image, draw, calling, f"calling at {stops}", _CALLING_Y, scroll, AMBER)

    _draw_clock(draw, now or datetime.now())
    return _threshold(image)


def _threshold(image: Image.Image) -> Image.Image:
    """Snap each pixel to fully-on/fully-off so no antialiasing fringe reaches the panel.

    A pixel survives if its brightest channel clears ``_THRESHOLD``; otherwise it goes
    black. Done with channel ops (not a Python pixel loop) so it stays cheap per frame.
    """
    r, g, b = image.split()
    brightest = ImageChops.lighter(ImageChops.lighter(r, g), b)
    mask = brightest.point(lambda p: 255 if p >= _THRESHOLD else 0)
    return Image.composite(image, Image.new("RGB", image.size, BLACK), mask)


def _draw_departure(
    draw: ImageDraw.ImageDraw, service: Service, *, y: int, mark: bool = False
) -> None:
    """Destination CRS code on the left (big), time in a right-hand column.

    ``mark`` draws a ``<`` after the code to flag the row whose calling points are shown.
    """
    colour = _status_colour(service)
    code_font = _font(_CODE_FONT)
    time_font = _font(_TIME_FONT)

    time_text = _headline_time(service)
    time_w = int(draw.textlength(time_text, font=time_font))
    time_x = SIZE - _MARGIN - time_w
    draw.text((time_x, y + 1), time_text, font=time_font, fill=colour)

    marker = "<"
    marker_w = int(draw.textlength(marker, font=code_font)) + 1 if mark else 0
    code = service.destination_crs or _abbreviate(service.destination or "-")
    code = _fit_words(draw, code_font, code, time_x - _MARGIN - 1 - marker_w)
    draw.text((0, y), code, font=code_font, fill=colour)
    if mark:
        code_w = int(draw.textlength(code, font=code_font))
        draw.text((code_w + 1, y), marker, font=code_font, fill=colour)


def _choose_stops_index(services: list[Service]) -> int | None:
    """Index of the first useful departure to show calling points for.

    The first *non-cancelled* service that actually has calling points — a cancelled
    train's stops aren't worth showing. Returns None if nothing qualifies.
    """
    return next(
        (i for i, s in enumerate(services) if not s.is_cancelled and s.calling_points),
        None,
    )


def _headline_time(service: Service) -> str:
    """Revised time for a delayed service (e.g. "13:28"), else the scheduled time.

    ``service.expected`` is "On time"/"Cancelled" or an actual HH:MM revision; only the
    latter contains a colon, so it stands in for the scheduled time when present.
    """
    expected = service.expected
    return expected if ":" in expected else service.time


def _abbreviate(name: str) -> str:
    for full, short in _ABBREVIATIONS.items():
        name = name.replace(full, short)
    return name


def _draw_clock(draw: ImageDraw.ImageDraw, when: datetime) -> None:
    clock_font = _font(_CLOCK_FONT)
    text = when.strftime("%H:%M")
    width = draw.textlength(text, font=clock_font)
    draw.text(((SIZE - width) // 2, _CLOCK_Y), text, font=clock_font, fill=AMBER)


def _draw_scrolling(image, draw, font, text, y, scroll, colour) -> None:
    text = text + "    "  # gap before the wrap
    total = int(draw.textlength(text, font=font))
    if total <= 0:
        return
    if total <= SIZE:
        draw.text((0, y), text, font=font, fill=colour)
        return
    strip = Image.new("RGB", (total, _STRIP_H), BLACK)
    ImageDraw.Draw(strip).text((0, 0), text, font=font, fill=colour)
    offset = scroll % total
    image.paste(strip, (-offset, y))
    image.paste(strip, (total - offset, y))


def _fit_words(draw: ImageDraw.ImageDraw, font, text: str, max_width: int) -> str:
    """Truncate to fit, preferring whole-word cuts over dangling part-words."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    # Drop trailing words until it fits.
    words = text.split(" ")
    while len(words) > 1:
        words.pop()
        candidate = " ".join(words)
        if draw.textlength(candidate, font=font) <= max_width:
            return candidate
    # A single long word: fall back to a hard character cut.
    word = words[0]
    while word and draw.textlength(word, font=font) > max_width:
        word = word[:-1]
    return word
