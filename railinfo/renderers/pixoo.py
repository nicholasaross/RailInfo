"""Render a :class:`~railinfo.domain.models.DepartureBoard` to a 64x64 image.

National-Rail dot-matrix look: amber text on black. Layout (64x64):

* rows 0-2  — up to three departures: ``CRS  P# HH:MM`` (destination code on the left;
  platform + time right-justified flush to the edge on the same row, colour = status). Codes
  keep names short so the font stays large and legible. A delayed service appends ``:MM`` of
  the revised minute and drops the ``P`` prefix to make room (e.g. ``2 13:25 :28``) — matching
  the Heltec's notation. **The station code is never truncated**: when room is tight (a marked
  and/or delayed row), the right-hand block degrades instead — dropping the platform, then the
  ``:MM`` minute — so the code always survives whole.
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
_FONT_PATH = Path(__file__).resolve().parents[2] / "Fonts" / "dot-matrix-regular.ttf"

BLACK = (0, 0, 0)
AMBER = (255, 176, 0)
ORANGE = (255, 110, 0)
RED = (255, 45, 35)

# One body size for everything (codes/times/calling) — it lands on whole pixels so the
# dot-matrix font thresholds crisply (see _threshold). The clock is doubled for emphasis.
_BODY_FONT = 10
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


def render_starting_image(now: datetime | None = None) -> Image.Image:
    """A minimal 'starting' placeholder shown until the first board fetch lands (cold start).

    The merged server fetches lazily, so for ~2s after launch there's no board yet; the Pixoo
    shows this (a label + the clock) instead of a blank panel.
    """
    image = Image.new("RGB", (SIZE, SIZE), BLACK)
    draw = ImageDraw.Draw(image)
    text = "starting"
    width = draw.textlength(text, font=_font(_BODY_FONT))
    draw.text(((SIZE - width) // 2, 2), text, font=_font(_BODY_FONT), fill=AMBER)
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
    """Destination CRS code on the left (big), platform + time in a right-hand column.

    The station code is never truncated to make room: ``mark`` (a ``<`` after the code,
    flagging the train whose calling points are shown) and a delayed service's wide ``:MM``
    suffix are absorbed by degrading the right-hand block, not the code — see
    :func:`_choose_layout`. The time uses tabular digits so columns line up across rows.
    """
    colour = _status_colour(service)
    code_font = _font(_CODE_FONT)
    time_font = _font(_TIME_FONT)

    code, right = _choose_layout(service, mark=mark)
    # Right-hand block hard against the edge. SIZE + 1 lands the digits' ink on the final
    # column — the +1 absorbs the font's right side bearing so there's no gap.
    _draw_time(draw, right, SIZE + 1, y, time_font, colour)
    draw.text((0, y), code, font=code_font, fill=colour)
    if mark:
        code_w = int(round(code_font.getlength(code)))
        draw.text((code_w + 1, y), "<", font=code_font, fill=colour)


def _choose_layout(service: Service, *, mark: bool) -> tuple[str, str]:
    """Pick the station code and the richest right-hand block that share one 64px row.

    The code (a 3-letter CRS, usually) is kept whole; the right block degrades to fit the
    space beside it (and beside the ``<`` marker, when ``mark``): full ``P# HH:MM[ :MM]`` →
    drop the platform → drop the ``:MM`` minute. Only a long destination *name* fallback
    (never a CRS) can force the code itself to be trimmed, as a last resort. Pure (font
    metrics only), so the never-truncate guarantee is unit-testable without rendering.
    """
    code_font = _font(_CODE_FONT)
    time_font = _font(_TIME_FONT)
    code = service.destination_crs or _abbreviate(service.destination or "-")
    marker_w = int(round(code_font.getlength("<"))) + 1 if mark else 0

    candidates = _right_candidates(service)
    budget = SIZE - int(round(code_font.getlength(code))) - marker_w - _MARGIN
    right = next((c for c in candidates if _tabular_width(time_font, c) <= budget), None)
    if right is None:
        # Even the narrowest block won't fit beside the whole code (a long name, not a CRS):
        # trim the code as a last resort so nothing overflows the panel.
        right = candidates[-1]
        room = SIZE - marker_w - _MARGIN - _tabular_width(time_font, right)
        code = _fit_words(code_font, code, room)
    return code, right


def _right_candidates(service: Service) -> list[str]:
    """Right-hand blocks from richest to poorest, so the code needn't shrink to fit one.

    The first equals :func:`_right_text`; the rest drop the platform, then the delay-minute
    suffix (``HH:MM :MM`` → ``HH:MM``), keeping at least the scheduled time.
    """
    candidates = [_right_text(service)]
    for shorter in (_headline_time(service), service.time):  # drop platform, then drop :MM
        if shorter not in candidates:
            candidates.append(shorter)
    return candidates


def _char_widths(font, text: str) -> list[int]:
    """Per-character widths with digits in a fixed widest-digit cell (tabular alignment)."""
    cell = max(int(round(font.getlength(d))) for d in "0123456789")
    return [cell if ch.isdigit() else int(round(font.getlength(ch))) for ch in text]


def _tabular_width(font, text: str) -> int:
    """Width of ``text`` as :func:`_draw_time` lays it out (tabular digit cells)."""
    return sum(_char_widths(font, text))


def _draw_time(draw: ImageDraw.ImageDraw, text: str, right_x: int, y: int, font, colour) -> int:
    """Draw ``text`` right-aligned to ``right_x`` with tabular (monospaced) digits.

    Each digit sits right-aligned in a fixed cell as wide as the widest digit, so the narrow
    "1" can't shift its neighbours — every digit column lines up across rows, like a real
    platform board. Non-digit glyphs (the colon, or a "—" fallback) keep their own width.
    Returns the block's left x.
    """
    widths = _char_widths(font, text)
    left = right_x - sum(widths)

    x = left
    for ch, width in zip(text, widths):
        # Right-align within the cell so digits' right edges (and thus columns) align.
        draw.text((x + width - int(round(font.getlength(ch))), y), ch, font=font, fill=colour)
        x += width
    return left


def _choose_stops_index(services: list[Service]) -> int | None:
    """Index of the first useful departure to show calling points for.

    The first *non-cancelled* service that actually has calling points — a cancelled
    train's stops aren't worth showing. Returns None if nothing qualifies.
    """
    return next(
        (i for i, s in enumerate(services) if not s.is_cancelled and s.calling_points),
        None,
    )


def _is_delayed(service: Service) -> bool:
    """True when there's a revised time that differs from the scheduled one."""
    return ":" in service.expected and service.expected != service.time


def _headline_time(service: Service) -> str:
    """Scheduled time, plus " :MM" of the revised minute when delayed (e.g. "13:25 :28").

    Mirrors the Heltec board's notation. ``service.expected`` is "On time"/"Cancelled" or an
    actual HH:MM revision; only the latter contains a colon, and only when it also differs
    from the scheduled time do we append the revised minute.
    """
    if _is_delayed(service):
        return f"{service.time} :{service.expected.split(':')[1]}"
    return service.time


def _right_text(service: Service) -> str:
    """Right-hand block: platform then time, like the Heltec ("P2 13:25" / "P2 13:25 :28").

    Dropped to just the time when the platform is unknown or the service is cancelled (a
    cancelled train's platform is moot, and the red colour already flags it). On a delayed row
    the leading "P" is dropped (bare platform number) to reclaim width — code + platform + the
    ":MM" suffix won't all fit on 64px, and we'd rather keep the station code intact.
    """
    time = _headline_time(service)
    if service.is_cancelled or not service.platform:
        return time
    prefix = service.platform if _is_delayed(service) else f"P{service.platform}"
    return f"{prefix} {time}"


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


def _fit_words(font, text: str, max_width: int) -> str:
    """Truncate to fit ``max_width`` px, preferring whole-word cuts over dangling part-words."""
    if font.getlength(text) <= max_width:
        return text
    # Drop trailing words until it fits.
    words = text.split(" ")
    while len(words) > 1:
        words.pop()
        candidate = " ".join(words)
        if font.getlength(candidate) <= max_width:
            return candidate
    # A single long word: fall back to a hard character cut.
    word = words[0]
    while word and font.getlength(word) > max_width:
        word = word[:-1]
    return word
