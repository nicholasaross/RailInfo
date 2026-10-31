# RailInfo CYD Portrait client

A single-screen MicroPython client for a **CYD** (ESP32-2432S028) mounted **portrait** in a
3D-printed stand — the
["ESP32 CYD 2.8" Panel de control"](https://www.makeronline.com/en/model/ESP32%20CYD%202.8%22%20Panel%20de%20control%20(Clima,%20Acciones%20y%20Luna)/278002.html)
model by [AmeliaCore](https://www.makeronline.com/en/user/personalInfo/f7f6f4a3-8894-4b3d-96ce-259832965d9a.html)
on Anycubic Makeronline (Creative Commons Public Domain) — with the USB/power end at the bottom. The stand has no openings
for the buttons, so there are no views to cycle: one fixed screen shows **every departure, split
by direction** — northbound in the top half, southbound in the bottom half. (Photo of it running:
the gallery in the [main README](../../README.md).)

It's the [CYD client](../cyd/README.md)'s renderer (colour dot-matrix, strip-blit, per-row status
colours) on a 240×320 portrait layout, fed by the server's **`split`** view.

## Display layout

240×320 portrait, colour on black:

```
Earlswood (Surrey)    ⧗ 11:05    <- header: station · "refreshing" hourglass (while stale) · clock
------------------------------
▲ Northbound                     <- section title (grey)
Peterborough        P1 11:43     <- up to 6 rows per half: destination left, platform + time
Peterborough        P1 12:13        right; the whole row is coloured by status
Peterborough           13:13        (amber on time / orange delayed / red cancelled)
------------------------------
▼ Southbound
Horsham          P2 11:42 :55    <- delayed: scheduled time + revised minute (orange)
Horsham             P2 12:12
Horsham            cancelled     <- cancelled (red)
```

- **Two equal halves**, 6 rows each. LDBWS only looks 2 hours ahead, so off-peak each half
  typically shows ~4 trains (2 an hour each way at Earlswood); the spare rows stay blank.
- An empty half shows **No trains**.
- Status by colour, as on the CYD: **amber** on time, **orange** delayed (`HH:MM :MM`, or just the
  scheduled time when LDBWS only says "Delayed"), **red** `cancelled`.
- **Font:** one clean size, **dotmatrix19** at 1×. The widest right-hand block (`P1 14:55 :58`) is
  96 px, leaving ~140 px for the destination; longer names are abbreviated (`London` → `Ldn` …)
  and then trimmed.

## How it works

1. Connects to WiFi (up to 5 attempts, with on-screen progress).
2. Every `POLL_INTERVAL_S` (default 5s) GETs `/board?view=split` and re-blits only the rows whose
   pixels changed, so a static board doesn't flicker.
3. Keeps the last good board if a fetch fails; after 3 failures in a row shows **Server error**;
   reconnects WiFi if it drops.
4. Shows **Starting up...** while the lazy server makes its first fetch, and the hourglass while
   the server reports the board `stale`.
5. Against a server without the `split` view it says so (**Server needs the split view**) rather
   than drawing two empty halves.

## Server side: the `split` view

`/board?view=split` returns the usual header keys plus two lists (up to 8 each):

```json
{"status": "ready", "stale": false, "station": "Earlswood (Surrey)", "crs": "ELD",
 "generated_at": "2026-10-31T11:32:17+00:00", "messages": [],
 "northbound": [{"time": "11:43", "expected": "On time", "destination": "Peterborough",
                 "platform": "1", "is_cancelled": false}],
 "southbound": [{"time": "11:42", "expected": "11:55", "destination": "Horsham",
                 "platform": "2", "is_cancelled": false}]}
```

`northbound` is the configured direction filter (`DIRECTION_FILTER_CRS=RDH` — "calls at Redhill
next"); `southbound` is the same CRS with the opposite filter type ("came via Redhill"). Redhill is
the next station on the only line through Earlswood, so between them the two halves cover every
departure (checked live: 4 + 4 = all 8, no overlap). Two LDBWS calls per refresh, no Service
Details.

## Files

| File | Role |
|------|------|
| `railinfo_client.py` | Main app (deploy as `main.py` to autostart) |
| `boards.py` | Pin/SPI config, portrait size + rotation, `init_display()` |
| `config.py` | WiFi creds, `SERVER_URL`, poll interval — **gitignored**, copy from `config.py.example` |
| `lib/ili9341.py` | The CYD's minimal ILI9341/ILI9342 driver, plus an optional `invert` for ST7789-variant CYDs |
| `lib/writer.py`, `lib/dotmatrix19.py` | Peter Hinch `Writer` + the Dot Matrix font (copies of the CYD's) |
| `deploy.ps1` | Copy everything to the device (`-Port` required; `-Autostart` installs as `main.py`) |
| `_smoketest.py` | Bring-up check: WiFi + one fetch + render |
| `_orient.py` | Bring-up probe: panel ID registers + numbered MADCTL test cards (see `setup_log.md`) |

## Configuration

```bash
cp config.py.example config.py   # then edit
```

`SERVER_URL` must be an **IP** (MicroPython can't resolve local hostnames) and point at a RailInfo
server that has the `split` view — live, the NAS container `http://192.168.1.10:8088/board`.

## Deploy

Needs `mpremote` on the host (`uv tool install mpremote`). The board enumerates as a **CH340**
USB-serial (here: **COM7**).

```powershell
pwsh deploy.ps1 -Port COM7              # copy lib + app + config to the device
pwsh deploy.ps1 -Port COM7 -Autostart  # ...and install as main.py + reset (runs on boot)
```

`-Port` is required: COM ports shuffle when boards are swapped, so confirm the device with
`esptool --port COMx flash-id` first.

## Firmware

MicroPython **`ESP32_GENERIC` v1.29.0**, flashed at **`0x1000`** (original ESP32, not the S3). This
unit's panel needs MADCTL **`0xE0`** for portrait with the USB at the bottom; another CYD may need a
different value (three panel controllers ship on this board) — run `_orient.py` and see
`setup_log.md`.
