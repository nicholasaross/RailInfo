# RailInfo Heltec e-ink client

A MicroPython client for the **Heltec Wireless Paper V1.2** (ESP32-S3, 2.13" 250×122
SSD1682 e-ink). It polls the RailInfo JSON API and renders a live National Rail departure
board in the RailInfo **Dot Matrix** font.

This is the Phase 4 "smarter display": where the Pixoo has frames *pushed* to it, the Heltec
*pulls* JSON from the RailInfo server (`python main.py --serve`) and renders on-device. It's
based on the read-only ESP/Bindicator project (WiFi connect/retry, the `depg0213` driver,
the board-config factory).

## How it works

1. On boot, connects to WiFi (up to 5 attempts, with on-screen progress).
2. Every `POLL_INTERVAL_S` (default 5s) does a tiny HTTP GET of `/board?view=<mode>` for the
   current PRG view (see **View modes**).
3. Renders the board into the framebuffer and **only does the ~1.5s e-ink refresh when the
   frame actually changed** (a framebuffer byte-compare). The board changes ~once a minute,
   so the panel stays still most of the time — no ghosting/wear from needless refreshes.
4. Keeps showing the last good board if a fetch fails; reconnects WiFi if it drops.

## View modes (PRG button)

The **PRG button (GPIO0)** cycles three views. The press is caught by a **pin interrupt**, so it
takes effect on the next ~5s poll **whether or not the board data changed** — a press landing
during the blocking fetch or the e-ink refresh is latched, not dropped:

1. **Departures** — landscape, London-bound only (the server's `DIRECTION_FILTER_CRS`), with a
   calling-points footer.
2. **All departures** — portrait, every direction.
3. **Arrivals** — portrait, by origin.

## Display layout

Landscape **departures** (250×122, black-on-white):

```
Earlswood (Surrey)          14:52   <- header: station + clock (dotmatrix9)
-----------------------------------
Peterborough         P1 14:55       <- up to 5 rows (dotmatrix19): station left,
Bedford                  cancelled      platform + time right-justified
Ldn St Pancras       P1 15:25
Cambridge            P3 15:42 :48   <- delayed: scheduled + revised minute
-----------------------------------
Calling: Redhill, Merstham, ...     <- calling-at for the first listed service (dotmatrix9)
```

The portrait views (**all** / **arrivals**) render into a 121×250 canvas and rotate 90° CW onto
the panel, using dotmatrix9 with the same right-justified `station … P# HH:MM` rows.

Status lives in the time column (e-ink has no colour): **on time** = scheduled time; **delayed**
= `HH:MM :MM` (scheduled, then the revised minute); **cancelled** = `cancelled`, right-justified.

## Files

| File | Role |
|------|------|
| `railinfo_client.py` | Main app (deploy as `main.py` to autostart) |
| `boards.py` | Heltec pin/SPI config + `init_display()` factory |
| `config.py` | WiFi creds, `SERVER_URL`, poll interval — **gitignored**, copy from `config.py.example` |
| `lib/depg0213.py` | SSD1682 e-ink driver (FrameBuffer subclass; vendored from ESP) |
| `lib/writer.py` | Peter Hinch `Writer` (renders bitmap fonts) |
| `lib/dotmatrix9.py`, `lib/dotmatrix19.py` | Dot Matrix fonts — 9 = header/footer/portrait, 19 = landscape rows (generated from `Fonts/dot-matrix-regular.ttf`) |
| `tools/gen_fonts.ps1` | Regenerate the font modules from the TTF (sizes 9 and 19) |
| `tools/font_to_py.py` | Vendored TTF→MicroPython converter (Peter Hinch, MIT) |
| `tools/tabular_digits.py` | Pads narrow digits (e.g. "1") so numerals share a width and times line up |
| `deploy.ps1` | Copy everything to the device |

## Configuration

```bash
cp config.py.example config.py   # then edit
```

```python
WIFI_SSID = "your-ssid"
WIFI_PASSWORD = "your-password"
SERVER_URL = "http://192.168.1.116:8000/board"   # dev box now; NAS IP later. Must be an IP.
POLL_INTERVAL_S = 5
```

> MicroPython can't resolve local hostnames, so `SERVER_URL` must use an **IP address**.

## Deploy

Needs `mpremote` on the host (`uv tool install mpremote`). The board enumerates as a Silicon
Labs CP210x (here: **COM3**).

```powershell
pwsh tools/gen_fonts.ps1                # (re)generate fonts if needed
pwsh deploy.ps1 -Port COM3              # copy lib + app + config to the device
```

To autostart on power-up, deploy the app as `main.py`:

```powershell
mpremote connect COM3 cp railinfo_client.py :main.py
mpremote connect COM3 reset
```

(`deploy.ps1` does this for you.)

## Server side

Run the API the client polls (from the RailInfo repo root):

```bash
uv run python main.py --serve --port 8000        # serves /board and /healthz
```

It refreshes from LDBWS every `--interval` seconds and serves the cached projection, so
client polls never hit the upstream API. On the NAS it runs as the `railinfo-server`
service in `docker-compose.yml`.

## Firmware

The board needs MicroPython (`ESP32_GENERIC_S3`, flashed at offset `0x0`). See
`setup_log.md` for the exact `esptool` flow.
