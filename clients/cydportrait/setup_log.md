# CYD Portrait (ESP32-2432S028) — RailInfo client bring-up log

## Hardware
- **Board:** a third CYD, **ESP32-2432S028**, for a 3D-printed portrait stand (Makeronline "ESP32
  CYD 2.8" Panel de control") — portrait, USB/power at the bottom, no openings for the buttons.
- **Chip:** **ESP32-D0WD-V3** rev v3.1 (dual core, 240 MHz, **no PSRAM**), 4 MB flash (mfr 0x5e,
  device 0x4016), MAC `04:b2:47:9c:b8:04`. ~165 KB free heap on MicroPython 1.29.0.
- **USB-serial:** **CH340** (`VID_1A86&PID_7523`), enumerated **COM7** — the only serial device
  attached at the time. COM numbers shuffle between swaps; always confirm.
- **Display:** 2.8" TFT on SPI, **native landscape (ILI9342-type)**, like the first CYD's H685 —
  see §3.

### Pin map (same as the other CYDs)
```
Display (SPI(1)/HSPI, 20MHz): SCK=14 MOSI=13 MISO=12  CS=15 DC=2 RST=4   backlight=21
Rear RGB LED (active LOW):    R=4 G=16 B=17   (all held high = off)
```

## 1. Flash MicroPython (2026-10-31)
The factory demo was wiped without a backup (user's call). Firmware:
**`ESP32_GENERIC-20260824-v1.29.0.bin`** (1,790,544 bytes) — the latest stable on
micropython.org/download/ESP32_GENERIC/ at bring-up. Original ESP32 → offset **`0x1000`**.

```powershell
esptool --port COM7 flash-id                     # ESP32-D0WD-V3, 4MB
esptool --port COM7 erase-flash
esptool --port COM7 --baud 460800 write-flash 0x1000 ESP32_GENERIC-20260824-v1.29.0.bin
mpremote connect COM7 exec "import sys; print(sys.implementation)"   # -> version (1, 29, 0)
```
- The firmware download needed the sandbox off; serial (esptool, mpremote) worked inside it.
- The first `mpremote` right after flashing failed with "could not enter raw repl" — the CH340's
  DTR/RTS reset the board mid-boot. Just retry.
- v1.29.0 release notes: the ESP32 port moves to IDF 5.5.2; the breaking changes are all on other
  ports. Nothing the client uses changed.

## 2. Panel ID registers (inconclusive — the visual test decides)
`_orient.ids()` reads the controller's ID registers over MISO at 1 MHz:
- RDID4 `0xD3` → `ff ff ff ff`, also with the ILI9341 `0xD9` index-register trick — not answered.
- RDDID `0x04` → `08 40 d9 ff`; allowing for the 1-bit read dummy → **`10 81 b3`** (ID2 bit 7
  set, as on ILITEK parts; not the ST7789's `85 85 52`).
- RDDST `0x09` decodes cleanly with the same 1-bit shift (booster on, 16 bpp, sleep out, display
  on, no inversion), so the read path works — the ID bytes are just module-maker OTP values.

## 3. Orientation: MADCTL `0xE0` (MV|MX|MY), RGB, no inversion
`_orient.py` cycles all 8 MADCTL MV/MX/MY combinations at 240×320, each a numbered test card
(full-frame border, "TOP" + arrow, R/G/B bars, "USB end"). Held portrait with the USB at the
bottom, **card 8 (`0xE0`)** was upright, un-mirrored, with the border complete; the bars read
R-G-B on black → no BGR bit, no inversion.

So this panel is **native landscape** — an MV state gives the 240×320 portrait — the same family
as the first CYD's ILI9342, whose landscape is `0x40` (MV clear). The H685 log's "MV fills
column-major / half-width" came from driving an MV-rotated ILI9342 with 320-wide windows; with true
240×320 windows, MV is simply how you get portrait on this panel. Locked in as
`ili9341.ROTATION_PORTRAIT`, used by `boards.py`.

## 4. Client bring-up
- **Server:** a new `split` view (`/board?view=split` → `northbound` / `southbound`; see the
  README). Against live LDBWS: 4 Peterborough (P1) north, 4 Horsham (P2) south — exactly the
  unfiltered board's 8.
- **Smoketest** (`mpremote connect COM7 run _smoketest.py`) against a dev-box server
  (`192.168.1.113:8000`): 240×320, sections at y=22 / 171, 6 rows per half, WiFi up (device DHCP
  **192.168.1.249**), board rendered. Layout and colours confirmed on the panel.
- **Stale hourglass** confirmed, aligned next to the clock, against a server run with
  `--stale-after 0` (every board stale).
- Installed as `:main.py` with `deploy.ps1 -Port COM7 -Autostart`; `mpremote reset` worked first
  time (no CH340 trouble), and the autostarted client polled `?view=split` every ~5s.
- Then pointed `config.py` at the NAS (`192.168.1.10:8088`). Until the NAS image has the `split`
  view the client shows "Server needs the split view"; it switches to the board by itself once the
  NAS serves it.
