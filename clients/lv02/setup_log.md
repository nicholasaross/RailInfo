# Luckyminer LV02 - RailInfo client bring-up log (2026-08-01)

## Hardware
- **Luckyminer LV02-250KH/S** BTC lottery-miner gadget (Amazon UK B0GFNKNPFP). It is a
  **LilyGo T-Display-S3 CLONE** (PCB silkscreen `LV02_30LCD`, 2024.12.23).
- **MCU:** ESP32-S3 (QFN56), **16MB** flash (Winbond 25Q128), **NO PSRAM** (`PSRAM chip not
  found` at boot). **Native USB-Serial/JTAG** (VID 303A) - no CH340. MAC `10:51:db:4c:de:18`.
- **Display:** 1.9" **170x320 ST7789**, panel `HD19006C30-V4`, driven by an **8-bit PARALLEL
  (i8080) bus - NOT SPI** (this was the whole bring-up saga; see the repo memory notes).
- Factory firmware = **NerdMiner V2** (open source). Full 16MB dump backed up to
  `lv02_factory.bin` (gitignored - licence keys + NVS WiFi). Restore: `esptool write-flash 0x0`.

## Verified pinout (= LilyGo T-Display-S3)
```
POWER_ON=15  BL=38  CS=6  DC=7  RST=5  WR=8  RD=9
data D0..D7 = 39,40,41,42,45,46,47,48   (GPIO43/44 are UART0, skipped)
buttons: BOOT=0, KEY=14 (two front buttons; side button = Reset)
```
POWER_ON(15) and BL(38) were found empirically (button-probe); the rest match the T-Display-S3
reference and were confirmed by an on-panel init + colour fill + the live client.

## Driver / geometry
- `lib/st7789.py` is a **parallel-i8080 ST7789 driver** (not the SPI one the other clients use).
  Same public API (`block`/`fill_rectangle`/`clear`/`color565`) so the RailInfo strip-blit
  renderer is a drop-in. Data bus + WR strobe are driven via `machine.mem32` to the S3 GPIO
  registers; the hot pixel loops are `@micropython.viper` (full-screen push < ~1s).
  Data-bus byte -> GPIO_OUT1 (0x60004010) bits 7,8,9,10,13,14,15,16 (mask 0x1E780).
- **Currently NATIVE PORTRAIT 170x320** (`boards.py`: rotation `0xC0` MX|MY, xoff=35, yoff=0,
  swap=False). This is the guaranteed-correct data order (no transpose). **Landscape (320x170)
  is still TODO** - it needs a transpose because the ST7789 RAMWR is always column-fast, so a
  320-wide strip overflows CASET (max 240). Do it like the Heltec's PortraitCanvas (render
  landscape, transpose 90deg in `block`), NOT via MADCTL MV alone (that garbled the data order).

## Flash / deploy
- MicroPython **ESP32_GENERIC_S3** (`D:\Projects\ESP\micropython_s3.bin`, v1.28) flashed at
  **`0x0`**. After flashing its USB-CDC re-enumerates (PID 4001), usually **COM7**.
- Deploy: `deploy.ps1 -Port COM7 [-Autostart]`. Display-only check: `_disptest.py`.
- **USB-Serial/JTAG WEDGES constantly** with mpremote (esp. on `reset`); recovery = physical
  unplug/replug. Most robust workflow: `mpremote cp ... :main.py` then **power-cycle to
  autostart** (zero live-USB dependency). Avoid `mpremote reset`.

## Status
Live end-to-end: WiFi startup screen -> live NAS board -> departures/all/arrivals views cycle on
the BOOT button. Portrait looks good; **landscape for the main board is the next task.**
