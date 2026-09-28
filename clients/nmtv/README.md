# RailInfo NM-TV client (NMTech NM-TV-MINER v1.0 "SmallTV")

A MicroPython RailInfo client for the NMTech **NM-TV** — a little desk gadget sold as an ESP32
Bitcoin "lottery miner" / desk clock, here repurposed as a fourth RailInfo display. Original
ESP32 (Sparkle IoT XH-32S module, no PSRAM), **1.54" 240×240 ST7789 IPS** TFT, and a
capacitive **touch pad on the case top** as its only input.

Same behaviour as the [CYD client](../cyd/README.md), which this is a direct port of: it polls
the RailInfo JSON server (`/board`) over WiFi every ~5s and renders the board in the Pixoo's
colour dot-matrix look — amber = on time, orange = delayed (`HH:MM :MM`), red = `cancelled` —
with per-region change detection (no flicker) and a scrolling "Calling:" footer. A **touch on
the pad** (or BOOT, if your unit has the button populated) cycles
`departures → all departures → arrivals`.
While the server reports the board **`stale`** (fetching fresh data after a wait), a small
hourglass shows next to the clock and the footer holds static; both clear when live data lands.

## Hardware notes (v1.0 board — differs from NMTech's published pinout!)

| Function | Pin | Notes |
|---|---|---|
| SCK / MOSI | GPIO14 / GPIO13 | `SPI(1)` (HSPI), mode 0, 20 MHz |
| CS / DC | GPIO15 / GPIO2 | as documented for the NM-TV-154 |
| RST | — | not wired; software reset |
| Backlight | **GPIO19 + GPIO21, BOTH active-low** | **must be driven low BEFORE panel init** |
| Touch | GPIO32 | bare capacitive plate ("TC" pad), read via `machine.TouchPad` |
| Button | GPIO0 | BOOT; footprint may be unpopulated |

The backlight needing *both* pins low — with nothing visible ever drawn while they're high —
is the trap that consumed this board's entire bring-up. See [setup_log.md](setup_log.md) for
the full story and for `_probe_interactive.py`, an interactive pin-hunting tool built along
the way.

## Flashing MicroPython (from the factory NMMiner firmware)

CH340 USB-serial; original ESP32, so firmware flashes at offset **0x1000**:

```powershell
esptool --port COM5 flash-id                                   # confirm plain ESP32
esptool --port COM5 read-flash 0x0 0x400000 nmminer_backup.bin  # back up the miner first!
esptool --port COM5 erase-flash
esptool --port COM5 --baud 460800 write-flash 0x1000 ESP32_GENERIC-*.bin
```

To restore the original miner: `esptool --port COM5 write-flash 0x0 nmminer_backup.bin`.

## Deploy

```powershell
Copy-Item config.py.example config.py   # then edit: WiFi creds + server IP (not hostname)
pwsh deploy.ps1 -Port COM5              # copy lib + app + config
mpremote connect COM5 run _smoketest.py # display + WiFi + live board end-to-end check
pwsh deploy.ps1 -Port COM5 -Autostart   # install as main.py and reset
```

`config.py` is gitignored (WiFi credentials + server IP). The fonts (`lib/dotmatrix19.py`)
and `lib/writer.py` are shared with the CYD client — regenerate via `../cyd/tools/gen_fonts.ps1`.
