# Regenerate the on-device Dot Matrix bitmap font modules from the shared TTF.
#
# The Heltec renders the board on-device with Peter Hinch's `Writer`, which needs the font as
# a MicroPython module rather than a TTF. We convert the SAME Fonts/dot-matrix-regular.ttf the
# server (Pixoo renderer) uses, so the typeface stays a single source of truth.
#
# - Only the two sizes the client uses are generated: 9 (header/footer/portrait rows) and 19
#   (landscape rows). Both are "clean" sizes — the dot-matrix grid lands on whole pixels only
#   at certain heights (8/9, 16-19, 25-27, 34); other sizes render with broken mid-glyph gaps.
# - Fonts are PROPORTIONAL (-x), for natural text, then tabular_digits.py pads narrow digits
#   (e.g. "1") on the right so all numerals share a width and times line up.
#
# Requires `uv` and network the first time (to fetch freetype-py into uv's cache).
# Usage:  pwsh clients/heltec/tools/gen_fonts.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $here "..\..\..")          # RailInfo repo root
$ttf  = Join-Path $root "Fonts\dot-matrix-regular.ttf"
$lib  = Join-Path $here "..\lib"
$conv = Join-Path $here "font_to_py.py"
$tab  = Join-Path $here "tabular_digits.py"

$sizes = 9, 19

foreach ($h in $sizes) {
    $outfile = Join-Path $lib "dotmatrix$h.py"
    Write-Output "Generating dotmatrix$h.py (proportional, tabular digits) ..."
    uv run --with freetype-py python $conv $ttf $h $outfile -x
    uv run --with freetype-py python $tab $outfile
}
Write-Output "Done."
