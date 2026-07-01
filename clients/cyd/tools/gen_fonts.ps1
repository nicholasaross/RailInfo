# Regenerate the on-device Dot Matrix bitmap font modules from the shared TTF (CYD client).
#
# The CYD renders the board on-device with Peter Hinch's `Writer`, which needs the font as a
# MicroPython module rather than a TTF. We convert the SAME Fonts/dot-matrix-regular.ttf the
# server (Pixoo renderer) and the Heltec client use, so the typeface stays a single source of
# truth across every display.
#
# - ONE size: 19. On the CYD's sharp TFT the dot-matrix only rasterises cleanly at small sizes
#   (19 lands on whole pixels; 22-38 do NOT — they look off-grid). The big departure rows are
#   drawn at 19 and INTEGER-scaled x2 in the client (railinfo_client.py BIG_SCALE) so the dots
#   stay square. So we ship just dotmatrix19 (same clean size the Heltec uses).
# - Fonts are PROPORTIONAL (-x), for natural text, then tabular_digits.py pads narrow digits
#   (e.g. "1") on the right so all numerals share a width and times line up.
#
# Requires `uv` and network the first time (to fetch freetype-py into uv's cache).
# Usage:  pwsh clients/cyd/tools/gen_fonts.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $here "..\..\..")          # RailInfo repo root
$ttf  = Join-Path $root "Fonts\dot-matrix-regular.ttf"
$lib  = Join-Path $here "..\lib"
$conv = Join-Path $here "font_to_py.py"
$tab  = Join-Path $here "tabular_digits.py"

$sizes = @(19)

foreach ($h in $sizes) {
    $outfile = Join-Path $lib "dotmatrix$h.py"
    Write-Output "Generating dotmatrix$h.py (proportional, tabular digits) ..."
    uv run --with freetype-py python $conv $ttf $h $outfile -x
    uv run --with freetype-py python $tab $outfile
}
Write-Output "Done."
