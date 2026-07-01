# CYD (ESP32-2432S028) — RailInfo client bring-up log

## Hardware
- **Board:** CYD "Cheap Yellow Display", **ESP32-2432S028** — the physical panel is marked
  **"H685"** on its edge.
- **Chip:** original **ESP32-D0WD-V3** (ESP32-WROOM-32 class, dual-core, **no PSRAM**, ~165 KB
  free heap on 1.28). CH340 USB-serial. MAC b4:bf:e9:03:e4:70.
- **Display:** 2.8" **320×240 ILI9342** colour TFT, SPI; backlight on GPIO21. **NOT ILI9341** —
  see the big note in §4. The ESP32-2432S028 ships in three display variants (ILI9341 / ILI9342
  / ST7789V); this unit is the ILI9342 (native landscape).
- **Touch:** XPT2046 resistive (separate SPI bus); IRQ on GPIO36 (used only as a tap source).
- **USB-serial:** **CH340** on **COM4** (contrast the Heltec's native-USB CP210x/S3 on COM3).

### Pin map (verified on this unit)
```
Display (ILI9342, SPI(1)/HSPI, 20MHz): SCK=14 MOSI=13 MISO=12  CS=15 DC=2 RST=4   backlight=21
Touch   (XPT2046):                     CLK=25 MOSI=32 MISO=39  CS=33  IRQ=36
Button: BOOT = GPIO0.  Touch IRQ (GPIO36) doubles as a "tap" press source.
```
- Use **`SPI(1)`** (HSPI — 14/13/12/15 are its native pins) at **20 MHz**. `SPI(2)` did not work,
  and 40 MHz produced garbled block writes on this unit.

## 1. Host tooling
`mpremote` via `uv tool install mpremote`. `esptool` in `D:\Projects\ESP\.venv\Scripts`.

## 2. Flash MicroPython (from scratch — board shipped with the factory demo)
Firmware: **`ESP32_GENERIC` v1.28** (generic ESP32 — **not** the S3 build). The original ESP32
flashes at offset **`0x1000`** (the bootloader lives below it), unlike the S3 which flashes at
`0x0`. Get the firmware from micropython.org/download/ESP32_GENERIC/.

```powershell
esptool --port COM4 flash-id                                   # confirm ESP32 (not S3)
esptool --port COM4 erase-flash
esptool --port COM4 --baud 460800 write-flash 0x1000 ESP32_GENERIC-*.bin
mpremote connect COM4 exec "import sys; print(sys.implementation)"
# -> micropython (1,28,0), ESP32_GENERIC
```
> Network + USB: disable the sandbox for the firmware download / erase / write steps.

## 3. Dot Matrix font → MicroPython bitmap module
Same pipeline as the Heltec, driven by `tools/gen_fonts.ps1` (`font_to_py.py -x` proportional,
then `tabular_digits.py`). **One clean size — dotmatrix19.**

Bring-up lesson: on this **sharp TFT** the dot-matrix TTF only rasterises crisply (dots on whole
pixels) at *small* sizes — 19 is clean, but 22/24/26/28/30/32/34/38 all look off-grid (the e-ink
Heltec hid this). So instead of a bigger font for the departure rows, the client draws them at 19
and **integer-scales ×2** (`railinfo_client.py BIG_SCALE`), turning each dot into a crisp 2×2
block. Small text (header/footer/lists) is 19 at 1×. Net: ship just `dotmatrix19` (same size the
Heltec uses).

```powershell
pwsh clients/cyd/tools/gen_fonts.ps1     # offline uses uv's cached freetype-py
```

## 4. Driver — and the ILI9341-vs-ILI9342 trap (the big bring-up lesson)
`lib/ili9341.py` — a minimal, purpose-built driver (standard Adafruit/rdagger ILI9341 init
sequence, 16-bit colour). Exposes only `block()` (push a pre-built **big-endian** RGB565 buffer
to a rectangle), `fill_rectangle()`, `clear()`. Text is **not** drawn by the driver — it's
rendered into a 1-bpp `framebuf` strip (`Writer` + Dot Matrix fonts) and colourised at blit time.

**This unit is an ILI9342, not an ILI9341** (the ESP32-2432S028 has 3 display variants). The
ILI9341 init sequence drives it fine, but the ILI9342 is **natively 320×240 landscape**, so:
- **`ROTATION = 0x40` (MADCTL MX only) — do NOT set the MV/transpose bit.** MV is how you'd get
  landscape on a *portrait-native ILI9341*; on the already-landscape ILI9342 it maps the screen
  to 240 wide → everything renders **half-width**. Verified: 0x40 gives a forward image with red
  in the physical top-left.
- **No BGR bit** — this is an RGB panel (pure R/G/B read correctly; setting BGR swaps red/blue).
- Fill-order gotcha that cost time: with MV set, `block()` fills **column-major** → varied
  content scrambles into diagonal stripes (solid fills survive, which masks it). With 0x40
  (no MV) it's row-major, matching `blit_strip`. If you ever re-enable MV, transpose the buffer.

Bring-up debugging path (for reference): backlight-only ✓ → solid fills ✓ but text garbled →
isolated to MV column-major fill → found half-width → researched "H685" → ILI9342 → 0x40 no-MV.

## 5. Rendering approach (bring-up notes)
No PSRAM → **no full-screen colour framebuffer**. Each region is a 1-bpp `Strip`
(`framebuf.FrameBuffer`, MONO_HLSB) that `Writer` draws into; `Board.blit_strip` expands the lit
pixels to the region's status colour (unlit → black) into a reused RGB565 scratch buffer and
`block()`s it out, **optionally integer-upscaling** (the departure rows are drawn into a
half-width source strip then blitted ×2). Per-region change detection (`Board._emit`) skips
regions whose bytes+colour are unchanged, so a static board doesn't re-blit / flicker. A full
repaint (`clear()` + all regions) happens only on entry and after a view change (`force=True`).

**Palette (tuned on-panel, as rendered TEXT):** this TFT's green is very luminous and thin
coloured strokes skew greener than solid swatches, so the Pixoo's `(255,176,0)` amber reads green
here. Verified values: on-time amber `(255,150,0)`, delayed orange `(255,60,0)`, cancelled red
`(255,0,0)` — well-separated so the three states stay distinct.

## 6. Client behaviour
- **Views (BOOT button / screen tap) — POLLED, not interrupt-driven.** The inputs are read in the
  ~5s wait loop: the **BOOT button by GPIO0 level** (edge high→low), and a **screen tap by READING
  the XPT2046** pressure (Z1) over its own SoftSPI (25/32/39, CS 33). **The touch IRQ line GPIO36
  is NOT usable** — measured on this unit it fires **~9 spurious interrupts/second** (level stays
  high), and a real tap does **not** cleanly pull it low; the GPIO0 IRQ never fired either. The
  original IRQ design auto-cycled the view every poll (phantom GPIO36 edges) and swallowed real
  BOOT presses via the shared debounce. Polling both (button level + XPT2046 Z1 > ~400) is
  reliable. Trade-off: a tap entirely within the ~1s blocking fetch can be missed (the poll covers
  the ~5s wait, almost all of each cycle).
- **Status by colour:** amber = on time, orange = delayed (`HH:MM :MM`), red = `cancelled`.
- **Scrolling calling-at footer** (departures view): when the "Calling: …" line is wider than the
  screen it's rendered into a wide off-screen strip and slid (animated by `board.tick_scroll`,
  passed as `Inputs.wait(on_tick=…)`, via two `framebuf.blit`s + one colourise); short lists draw
  static. Two gotchas found here: (1) the ~50 ms footer blit was **starving input polling** (~half
  of BOOT/tap presses dropped) — fixed by decoupling in `Inputs.wait`: poll input every
  `INPUT_POLL_MS` (15 ms) but only scroll every `FOOT_SCROLL_MS`, with an extra input poll right
  after each blit. (2) **Both** `inputs.wait` sites in `run()` must pass `board.tick_scroll` — the
  main end-of-loop one was missing it, so the footer never moved during normal running.
- Deploy as `:main.py` (autostart) via `deploy.ps1 -Autostart`.
- **Live server:** polls the `railinfo` container on the NAS (`192.168.1.10:8088`) via
  `config.py SERVER_URL`. No server changes were needed — the three views already existed.

## Notes / gotchas
- Enumerated on **COM4** (CH340). Always confirm `flash-id` reports plain ESP32, and flash at
  **`0x1000`** (not `0x0`).
- MicroPython can't resolve hostnames → `SERVER_URL` must be an IP.
- No `requests`/`urequests` on a fresh flash; the client uses the same tiny dependency-free
  `http_get_json` over `socket` (HTTP/1.0, Connection: close) as the Heltec.
- Font regen needs freetype-py (cached in uv): `uv run --offline --with freetype-py ...`.
