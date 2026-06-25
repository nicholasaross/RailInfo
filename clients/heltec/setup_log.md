# Heltec Wireless Paper V1.2 — RailInfo client bring-up log

## Hardware
- **Board:** Heltec Wireless Paper V1.2 (box-fresh unit, distinct from the one in the ESP repo)
- **Chip:** ESP32-S3 (QFN56) rev v0.2, 8MB flash (GD), no PSRAM
- **Display:** 2.13" 250×122 e-ink, SSD1682 controller (panel E0213A367)
- **USB-serial:** Silicon Labs CP210x on **COM3**
- **MAC:** 44:1b:f6:f7:50:a0

## 1. Host tooling
`mpremote` installed via `uv tool install mpremote`. `esptool` v5.2.0 already present in
`D:\Projects\ESP\.venv\Scripts`.

## 2. Flash MicroPython (from scratch — board shipped blank)
Firmware: `ESP32_GENERIC_S3 v1.28.0` (the proven `micropython_s3.bin` from the read-only ESP
repo). ESP32-S3 flashes at offset **0x0**.

```powershell
esptool --port COM3 flash-id                              # confirm ESP32-S3
esptool --port COM3 erase-flash
esptool --port COM3 --baud 460800 write-flash 0x0 micropython_s3.bin
mpremote connect COM3 exec "import sys; print(sys.implementation)"
# -> micropython (1,28,0), ESP32_GENERIC_S3, ~226KB free RAM
```

## 3. Dot Matrix font → MicroPython bitmap modules
Converted `Fonts/dot-matrix-regular.ttf` with Peter Hinch's `font_to_py.py`, **proportional**
(`-x`), then `tools/tabular_digits.py` pads narrow digits (e.g. "1") so numerals share a width
and times line up. Driven by `tools/gen_fonts.ps1`.

The client ships **two** sizes (the dot-matrix grid only lands cleanly on whole pixels at
certain heights — 8/9, 16–19, 25–27, 34): **dotmatrix9** (header, footer, portrait rows) and
**dotmatrix19** (landscape departure rows). The size-exploration leftovers (10/16/17/18/20–30
and the `dm*mono` experiments) have been removed.

## 4. Driver
`lib/depg0213.py` vendored from the ESP repo and refactored to **subclass
`framebuf.FrameBuffer`** so Peter Hinch's `Writer` can render the Dot Matrix font into it.
SSD1682 command sequence unchanged. Full refresh ~1.5s.

## 5. Bring-up results
- `demo.py` — rendered the every-cell capability grid + capacity summary. ✓
- `_smoketest.py` — WiFi connected (IP 192.168.1.139, RSSI −71), fetched live board from the
  dev-box server (`192.168.1.116:8000`), rendered, refreshed; second cycle detected no change
  and skipped the refresh. ✓
- Full `railinfo_client.py` loop — polls every 5s; logs `panel refreshed` only when the frame
  changes (~once/min), else `frame unchanged, skip refresh`. ✓

## 6. Final client behaviour
- **Views (PRG / GPIO0):** a pin **interrupt** cycles departures (landscape) → all departures
  (portrait) → arrivals (portrait); a press is honoured on the next ~5s poll regardless of
  whether the data changed (presses during the fetch/refresh are latched, not dropped).
- **Rows:** station (destination/origin) left; **platform + time** right-justified (e.g.
  `P1 14:55`). Status in the time column: on time = scheduled; delayed = `HH:MM :MM`
  (scheduled + revised minute); cancelled = `cancelled`, right-justified.
- Deployed as `:main.py` (autostart). The device carries only the production files: `main.py`,
  `boot.py`, `config.py`, `boards.py`, and `lib/{depg0213,writer,dotmatrix9,dotmatrix19}`.
- **Live server:** the client polls the `railinfo` container on the NAS (`192.168.1.10:8088`)
  via `config.py SERVER_URL` — the dev-box `192.168.1.116:8000` in §5 was bring-up only. See the
  client `README.md` for the current server topology and the "Starting up…" status screen.

## Notes / gotchas
- The board enumerated on **COM3** (the ESP repo's older unit was COM4) — always confirm the
  port and that `flash-id` reports ESP32-S3.
- MicroPython can't resolve hostnames → `config.py` `SERVER_URL` must be an IP.
- No `requests`/`urequests` on a fresh flash; the client uses a tiny dependency-free
  `http_get_json` over `socket` (HTTP/1.0, Connection: close).
