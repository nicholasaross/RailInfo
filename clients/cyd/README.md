# RailInfo CYD colour client

A MicroPython client for the **CYD** — "Cheap Yellow Display", board **ESP32-2432S028** (original
ESP32, 2.8" 320×240 colour TFT + XPT2046 resistive touch). It polls the RailInfo JSON API and
renders a live National Rail departure board in the RailInfo **Dot Matrix** font.

> **Display variant matters.** The ESP32-2432S028 ships with one of three controllers (ILI9341,
> ILI9342, ST7789V). The unit this was built on (panel marked **"H685"**) is an **ILI9342**
> (native 320×240 landscape), driven on **`SPI(1)` at 20 MHz** with MADCTL **`0x40` (no transpose
> bit)**. A different variant needs different `boards.py` / `ili9341.py` settings — see
> `setup_log.md`.

It's a **hybrid** of the other two clients:

- Like the **Heltec** e-ink client it *pulls* JSON from the RailInfo server (`--serve`), cycles
  three views, and reuses the same Dot Matrix font pipeline (`font_to_py` → `Writer`).
- Like the **Pixoo** it renders the **colour dot-matrix** National-Rail look — amber on black,
  with **per-row status colours** (amber on time, orange delayed, red cancelled).

## How it works

1. On boot, connects to WiFi (up to 5 attempts, with on-screen progress).
2. Every `POLL_INTERVAL_S` (default 5s) does a tiny HTTP GET of `/board?view=<mode>` for the
   current view (see **View modes**).
3. Renders the board and **only re-blits regions whose pixels actually changed** — a static
   board doesn't flicker, and the poll can stay short.
4. Keeps showing the last good board if a fetch fails; reconnects WiFi if it drops.
5. While the (lazy) server warms up its first fetch it replies `{"status": "starting"}`; the
   client shows a brief **"Starting up…"** screen until the real board lands.

### Rendering (why it's strip-based)

The original ESP32 has **no PSRAM**, so a full 320×240 RGB565 framebuffer (~150 KB) won't fit.
Instead each region (header, each row, footer) is drawn with `Writer` into a small **1-bpp
`Strip`** framebuffer, then colourised to RGB565 and pushed to the panel via the ILI9341 driver's
`block()`. This reuses the exact font pipeline the Heltec uses while keeping memory tiny.

## View modes (button **or** tap)

Input is hybrid: the **BOOT button (GPIO0)** *and* a **screen tap** both cycle the view. Both are
**polled** in the ~5s wait loop — the button by GPIO0 level, the tap by reading the XPT2046 touch
controller's pressure over SoftSPI. (The XPT2046 IRQ line, GPIO36, is *not* used: on this board it
fires spuriously ~9×/s and a real tap doesn't pull it low — see `setup_log.md`.)

1. **Departures** — big bold rows (2×-scaled dot-matrix), London-bound only (the server's
   `DIRECTION_FILTER_CRS`), with a calling-points footer.
2. **All departures** — dense list (1× dot-matrix), every direction.
3. **Arrivals** — dense list, by origin.

## Display layout

Landscape **departures** (320×240, colour on black):

```
Earlswood (Surrey)              14:52     <- header: station + clock (dotmatrix19 x1, amber)
------------------------------------------
Peterborough           P1 14:55           <- up to 4 big rows (dotmatrix19 x2): destination
Bedford                   cancelled           left, platform + time right. Whole row is
London St Pancras      P1 15:25               coloured by status (amber/orange/red).
Cambridge              P3 15:42 :48       <- delayed: scheduled + revised minute
------------------------------------------
Calling: Redhill, Merstham, ...           <- calling-at for the first listed service (x1);
                                              scrolls horizontally when wider than the screen
```

**All** / **Arrivals** use the 1× dotmatrix19 for ~9 rows with the same right-justified
`destination … P# HH:MM` layout (arrivals show the origin and arrival time).

**Fonts:** one clean size — **dotmatrix19**. The big departure rows are that font drawn at 19 and
**integer-scaled ×2** (`BIG_SCALE`) so the dots stay square; small text is 1×. (On this sharp TFT
the dot-matrix only rasterises cleanly at ≤~19; larger point sizes look off-grid.)

Status is shown by **colour** (unlike the mono e-ink Heltec), tuned for this panel's very green
TFT: **amber** `(255,150,0)` = on time, **orange** `(255,60,0)` = delayed (`HH:MM :MM` — scheduled,
then the revised minute), **red** `(255,0,0)` = `cancelled`.

## Files

| File | Role |
|------|------|
| `railinfo_client.py` | Main app (deploy as `main.py` to autostart) |
| `boards.py` | CYD pin/SPI config + `init_display()` factory |
| `config.py` | WiFi creds, `SERVER_URL`, poll interval — **gitignored**, copy from `config.py.example` |
| `lib/ili9341.py` | Minimal ILI9341/ILI9342 SPI driver (init + `block()` RGB565 blit + fill) |
| `lib/writer.py` | Peter Hinch `Writer` (renders bitmap fonts into a framebuf) |
| `lib/dotmatrix19.py` | The one Dot Matrix font (size 19); big rows are it scaled ×2 (generated from `Fonts/dot-matrix-regular.ttf`) |
| `tools/gen_fonts.ps1` | Regenerate the font module from the TTF (size 19) |
| `tools/font_to_py.py`, `tools/tabular_digits.py` | Vendored TTF→MicroPython converter + tabular-digit padder |
| `deploy.ps1` | Copy everything to the device (`-Autostart` installs as `main.py`) |
| `_smoketest.py` | Bring-up check: WiFi + one fetch + render |

## Configuration

```bash
cp config.py.example config.py   # then edit
```

```python
WIFI_SSID = "your-ssid"
WIFI_PASSWORD = "your-password"
SERVER_URL = "http://192.168.1.10:8088/board"   # the NAS container; an IP, not a hostname
POLL_INTERVAL_S = 5
```

> MicroPython can't resolve local hostnames, so `SERVER_URL` must use an **IP address**.

## Deploy

Needs `mpremote` on the host (`uv tool install mpremote`). The board enumerates as a **CH340**
USB-serial (here: **COM4**).

```powershell
pwsh tools/gen_fonts.ps1                # (re)generate fonts if needed
pwsh deploy.ps1 -Port COM4              # copy lib + app + config to the device
pwsh deploy.ps1 -Port COM4 -Autostart  # ...and install as main.py + reset (runs on boot)
```

## Server side

Identical to the Heltec: the client polls RailInfo's `/board` JSON API, live the merged
**`railinfo` container on the NAS** (`192.168.1.10:8088`). For local testing run
`uv run python main.py --serve --port 8000` on the dev box and point `SERVER_URL` at it. No server
changes were needed to add this client — the three views were already served.

## Firmware

The board needs MicroPython (**`ESP32_GENERIC`**, generic ESP32, flashed at offset **`0x1000`** —
note: *not* `0x0`, which is the S3). See `setup_log.md` for the exact `esptool` flow.
