"""Render a RailInfo ``/board`` payload to the Apex Pro TKL's 128×40 monochrome OLED.

GameSense's built-in text handler only fits two lines on this panel, so instead we draw our
own bitmap and push it as raw ``image-data-128x40`` (see ``oled_client.py``). Drawing it
ourselves lets us pack **four departure rows** in the DanielHartUK Dot Matrix font (and the
same threshold-to-pure-pixels trick the Pixoo/e-ink boards use), so the keyboard matches the
rest of the family.

No scrolling: the OLED's refresh rate can't animate a marquee smoothly, so the whole 40px
height goes to showing more services rather than one service's calling points. The panel is
1-bit — no colour to encode status (unlike the Pixoo) — so status rides in the *text*: the
delay notation ``HH:MM :MM`` and ``CANC``, like the e-ink board.

Layout (128 wide × 40 tall) — four rows at 10px pitch::

    ┌────────────────────────────────────────┐
    │ Bedford                       P1 12:12  │
    │ London Blackfriars               12:42  │
    │ Bedford                       P1 13:12  │
    │ Three Bridges                 P2 13:20  │
    └────────────────────────────────────────┘

The Dot Matrix face rasterises cleanly at size 10 (the size the Pixoo uses); larger sizes land
off the pixel grid and look broken, so every row uses 10.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 128, 40
_FONT_PATH = Path(__file__).resolve().parents[2] / "Fonts" / "dot-matrix-regular.ttf"

# Pixels dimmer than this (0..255) are the TTF's antialiasing fringe → snapped off, so only
# crisp dots reach the panel. Same idea as railinfo/renderers/pixoo.py:_threshold.
_THRESHOLD = 96

_ROW_FONT = 10        # the one size the Dot Matrix face renders crisply at (as on the Pixoo)
_ROW_PITCH = 10       # 4 rows × 10px = the full 40px height
_MAX_ROWS = 4
_TOP = 0              # row 1 baseline; 0 keeps the caps' top pixel row on-panel (not clipped)
_MARGIN = 1           # keep ink off the extreme edge columns
_GAP = 3              # min gap between a row's left text and its right-hand block

# Shorten long tokens so a truncated destination still reads (order matters).
_ABBREVIATIONS = {
    " International": " Intl",
    " Airport": " Apt",
    " Parkway": " Pkwy",
    " Junction": " Jn",
    " Central": " Ctl",
}


@lru_cache(maxsize=2)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONT_PATH), size)


def _abbreviate(name: str) -> str:
    for full, short in _ABBREVIATIONS.items():
        name = name.replace(full, short)
    return name


def _is_delayed(svc: dict) -> bool:
    exp = (svc.get("expected") or "").strip()
    return ":" in exp and exp != svc.get("time")


def _right_block(svc: dict) -> str:
    """Platform + time on the right, matching the e-ink board's notation.

    On time: ``P1 12:12``. Delayed: ``12:12 :15`` (platform dropped for width, revised minute
    appended). Cancelled: ``CANC``.
    """
    time = svc.get("time", "--:--")
    if svc.get("is_cancelled") or (svc.get("expected") or "").lower() == "cancelled":
        return "CANC"
    if _is_delayed(svc):
        return f"{time} :{svc['expected'].split(':')[1]}"
    platform = svc.get("platform")
    return f"P{platform} {time}" if platform else time


def _char_widths(font: ImageFont.FreeTypeFont, text: str) -> list[int]:
    """Per-character widths with digits in a fixed widest-digit cell (tabular alignment).

    Mirrors ``railinfo/renderers/pixoo.py``: the narrow "1" gets the same cell as "4", so the
    time columns line up across rows like a real platform board.
    """
    cell = max(int(round(font.getlength(d))) for d in "0123456789")
    return [cell if ch.isdigit() else int(round(font.getlength(ch))) for ch in text]


def _tabular_width(font: ImageFont.FreeTypeFont, text: str) -> int:
    return sum(_char_widths(font, text))


def _draw_tabular(draw: ImageDraw.ImageDraw, text: str, right_x: int, y: int,
                  font: ImageFont.FreeTypeFont) -> None:
    """Draw ``text`` right-aligned to ``right_x`` with each digit in a fixed cell."""
    widths = _char_widths(font, text)
    x = right_x - sum(widths)
    for ch, width in zip(text, widths):
        # Right-align each glyph within its cell so digits' right edges (columns) align.
        draw.text((x + width - int(round(font.getlength(ch))), y), ch, font=font, fill=255)
        x += width


def _fit(font: ImageFont.FreeTypeFont, text: str, max_width: int) -> str:
    """Trim ``text`` to fit ``max_width`` px, dropping whole words then characters."""
    if font.getlength(text) <= max_width:
        return text
    words = text.split(" ")
    while len(words) > 1:
        words.pop()
        if font.getlength(" ".join(words)) <= max_width:
            return " ".join(words)
    word = words[0]
    while word and font.getlength(word) > max_width:
        word = word[:-1]
    return word


def _draw_row(draw: ImageDraw.ImageDraw, svc: dict, y: int) -> None:
    """Destination on the left, platform+time hard against the right edge."""
    font = _font(_ROW_FONT)
    right = _right_block(svc)
    right_w = _tabular_width(font, right)
    _draw_tabular(draw, right, WIDTH - _MARGIN, y, font)

    dest = _abbreviate(svc.get("destination") or "?")
    dest = _fit(font, dest, WIDTH - _MARGIN - right_w - _GAP - _MARGIN)
    draw.text((_MARGIN, y), dest, font=font, fill=255)


def render_image(board: dict, *, rows: int = _MAX_ROWS) -> Image.Image:
    """Render the board to a 1-bit (mode ``"1"``) 128×40 image with up to ``rows`` services."""
    image = Image.new("L", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(image)

    if board.get("status") == "starting":
        draw.text((_MARGIN, _TOP), f"{board.get('crs') or ''} starting...".strip(),
                  font=_font(_ROW_FONT), fill=255)
    else:
        services = board.get("services") or []
        if not services:
            draw.text((_MARGIN, _TOP), "No departures", font=_font(_ROW_FONT), fill=255)
        for i, svc in enumerate(services[:rows]):
            _draw_row(draw, svc, _TOP + i * _ROW_PITCH)

    return image.point(lambda p: 255 if p >= _THRESHOLD else 0).convert("1")


def pack_1bit(image: Image.Image) -> list[int]:
    """Pack a mode-``"1"`` 128×40 image into GameSense's 640-byte image-data array.

    Row-major from the top-left, most-significant-bit first, a ``1`` bit = a lit pixel — the
    format the ``screened-128x40`` handler expects.
    """
    px = image.load()
    out = bytearray(WIDTH * HEIGHT // 8)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if px[x, y]:
                out[(y * WIDTH + x) >> 3] |= 0x80 >> (x & 7)
    return list(out)


def frame_bytes(board: dict, *, rows: int = _MAX_ROWS) -> list[int]:
    """Convenience: render ``board`` and return the 640-int image-data array."""
    return pack_1bit(render_image(board, rows=rows))
