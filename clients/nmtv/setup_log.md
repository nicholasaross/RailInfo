# NM-TV-MINER v1.0 — RailInfo client bring-up log (2026-07-18)

## Hardware
- **NMTech NM-TV** "SmallTV" desk gadget, sold as an ESP32 BTC lottery miner running NMMiner.
  Board silkscreen: **NM-TV-MINER v1.0**. ESP32 module: **Sparkle IoT XH-32S** (plain
  ESP32-D0WD-V3, no PSRAM, 4MB flash), CH340 USB-serial (**COM5**), u.FL WiFi antenna.
- **Display:** 1.54" 240×240 **ST7789 IPS**, 10-pin FPC marked `HD154010C10-V3 JY`, in the
  connector marked **FPC2** (an unpopulated 12-pin ZIF marked FPC1 sits on the board top).
- **Input:** a bare capacitive plate on the case top, wired to the board's **"TC"** pad →
  **GPIO32**, read with `machine.TouchPad` (no sensor chip). BOOT button footprint present
  but may be unpopulated. RST button populated.
- Factory firmware: **NMMiner v1.8.20** (TFT_eSPI + LVGL; PlatformIO env `nm-tv-154` per
  strings in the dump). Full 4MB dump taken before erasing — restoring it (`write-flash 0x0
  dump.bin`) brings the miner back completely, which was used mid-bring-up to prove the
  hardware was still healthy.

## Verified pin map (v1.0)
```
ST7789: SPI(1)/HSPI mode 0 @ 20MHz  SCK=14 MOSI=13  CS=15 DC=2  RST=none (SWRESET)
Backlight: GPIO19 AND GPIO21, BOTH ACTIVE LOW, set LOW BEFORE init  (≈300ms settle)
Touch: GPIO32 capacitive (baseline ~860, finger drops it ~190; threshold = baseline - max(80, base/5))
MADCTL 0x00, xoff/yoff 0, INVON, RGB — verified: R/G/B bars correct, marker top-left, no clipping.
```

## The bring-up story (read this before trusting any NM-TV documentation)

NMTech's published NM-TV-154 custom-firmware guide gives: CS=15 DC=2 SCK=14 MOSI=13,
`TFT_BL 19` (active LOW), `TFT_PWER_PIN 21`. On this v1.0 board **the data pins are right,
and 19/21 really are the backlight pins — but BOTH are active-low**, and nothing whatsoever
is visible unless both are low. Driving 19 low with 21 high (the literal reading of the docs)
lights nothing.

That one detail produced a spectacularly misleading debug session:

1. Initial bring-up on the documented pins "showed nothing" → assumed wrong pins.
2. Backlight GPIO sweeps (every safe pin, then every pair pattern) showed nothing → assumed
   backlight hardwired, data path wrong.
3. Display bus/DC/CS brute-force sweeps DID paint the panel white — invisibly (backlight
   off). When a sweep happened to pull 19/21 low, the backlight blinked and *revealed* the
   white already in RAM. Those blinks were misread as hits for whatever combo was executing
   at that moment, yielding a confidently "verified" wrong answer (DC=19/CS=21) that then
   failed every cold-start reproduction.
4. The tell was the user spotting that the glow was "three lights at the base of the screen"
   — the backlight LED chain — plus full-screen flashes earlier. Draw-first-then-light-the-
   backlight testing untangled it in two runs.

Lessons, should another mystery ESP32 display board turn up:
- **Pin the backlight state (all candidate combinations) while probing the data path** — a
  correct data-path hit is invisible under a dead backlight, and a backlight blink over stale
  panel RAM looks exactly like a data-path hit.
- Panel RAM persists across ESP32 resets while USB power stays up: "the screen shows my
  pattern" only proves *something once wrote it*, not that the current code did.
- `_probe_interactive.py` + `probe_one.py` (kept in this folder) drive the sweep from the
  host with per-combo user confirmation; the additive (delta-debugging) mode is the safe one
  — subtractive testing cascades failures once the panel gets broken mid-sequence.
- The factory-firmware dump is the hardware sanity anchor: restore, confirm the screen, and
  every "did our experiments break it?" fear evaporates.

## Flash / deploy facts
- `esptool --port COM5` (CH340). MicroPython `ESP32_GENERIC` at offset **0x1000**;
  `D:\Projects\ESP\micropython.bin` (v1.27.0) is the image used.
- NOTE: **COM5 is also what the second CYD enumerates as** — only one of the two CH340
  devices can be attached at a time, or Windows will shuffle the numbers. Check
  `esptool flash-id` + the connected hardware before flashing anything.
- Factory NMMiner dump lives outside the repo (it embeds NMTech licence keys and, in NVS,
  whatever WiFi credentials the device held). Keep the backup private.
- Deploy: `deploy.ps1 -Port COM5 [-Autostart]`; smoketest: `_smoketest.py`; display-only
  check: `_displaytest.py`. Device end-state: `boards/config/main/railinfo_client.py` +
  `lib/{st7789,writer,dotmatrix19}.py`.

## Post-deploy "crash" that wasn't (2026-07-18)
After the autostart install the board appeared frozen (no touch, stale clock). Cause: the
deploy script's final `mpremote reset` silently didn't take, so the device sat at the REPL
with `main.py` never started, displaying the last frame of a killed test run. **A frozen
NM-TV straight after deploy = check for that first** (power-cycle; the screen persists
whatever was last drawn, so a static image proves nothing about what's running).
`deploy.ps1` now checks the reset's exit code and says what to do if it fails. Autostart from
a genuine hard reset verified (boot log + `touch baseline ...` startup print captured over
serial).

## Client behaviour deltas vs the CYD client
- 240px-wide screen: same layout code (it keys off `display.width`); destination names
  truncate harder on the big rows. Vertical layout identical (both panels are 240 tall).
- Input = TC capacitive pad (GPIO32 TouchPad, startup-derived threshold) + BOOT poll; no
  XPT2046, no touch SPI.
- Backlight: GPIO21 (pwr) is a held-low power enable; GPIO19 (bl) is now **PWM-dimmed**
  (`boards.set_backlight`, `BL_BRIGHTNESS`, default 90%). The factory NMMiner firmware drives
  the backlight via LEDC/PWM (a "Brightness 0-100" setting — confirmed in a firmware dump),
  whereas the original client held bl at constant DC low. That constant DC drive made the
  backlight LED string glare as "obvious LEDs" at the base of the panel; PWMing the active-low
  line (100% == pin held low == the old full-on) removed the glare. Verified on unit 2
  (2026-07-31, factory image backed up to `nmtv_unit2_factory_v1.8.26.bin`, gitignored).
