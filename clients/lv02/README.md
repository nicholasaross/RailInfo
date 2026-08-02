# RailInfo LV02 client (Luckyminer LV02 — LilyGo T-Display-S3 clone)

A MicroPython RailInfo client for the **Luckyminer LV02** — another desk gadget sold as a
Bitcoin "lottery miner", here repurposed as a fifth RailInfo display. Under the marketing it is
a **LilyGo T-Display-S3 clone**: an **ESP32-S3** (16 MB flash, **no PSRAM**, native USB-Serial/
JTAG) driving a 1.9" **170×320 ST7789** over an **8-bit parallel (i8080) bus — not SPI**.

Same behaviour as the [CYD](../cyd/README.md)/[NM-TV](../nmtv/README.md) clients (this reuses the
NM-TV's `railinfo_client.py` unchanged): it polls the RailInfo JSON server (`/board`) over WiFi
every ~5s and renders the board in the Pixoo's colour dot-matrix look — amber = on time, orange =
delayed (`HH:MM :MM`), red = `cancelled` — with per-region change detection and a scrolling
"Calling:" footer. The **BOOT button (GPIO0)** cycles `departures → all departures → arrivals`.

## Hardware notes

The panel is **parallel, not SPI** — this is the whole story of the bring-up. Every SPI probe was
doomed; recognising the board as a T-Display-S3 clone is what unlocked it (see
[setup_log.md](setup_log.md)). Verified pinout (= LilyGo T-Display-S3):

| Function | Pin(s) |
|---|---|
| Panel power (`LCD_POWER_ON`) | GPIO15 |
| Backlight (`LCD_BL`) | GPIO38 |
| CS / DC / RST | GPIO6 / GPIO7 / GPIO5 |
| WR / RD | GPIO8 / GPIO9 |
| Data bus D0–D7 | GPIO39, 40, 41, 42, 45, 46, 47, 48 |
| Buttons | BOOT=GPIO0, KEY=GPIO14 (side button = Reset) |

`lib/st7789.py` is a **purpose-built parallel-i8080 ST7789 driver** — same public API
(`block`/`fill_rectangle`/`clear`/`color565`) as the SPI drivers, so the shared renderer is a
drop-in. The data bus + WR strobe are driven via `machine.mem32` to the ESP32-S3 GPIO registers,
and the hot pixel loops are `@micropython.viper`. Because the ST7789 RAMWR is always column-fast
(a 320-wide strip would overflow CASET's 240 max), **landscape is done with a 90° transpose in
the driver** (`_blit_t`, `landscape=True` in `boards.py`), not via MADCTL `MV` (which garbles the
data order).

## Flashing MicroPython (from the factory NerdMiner firmware)

Native USB-Serial/JTAG (no CH340), ESP32-S3, so MicroPython flashes at offset **0x0**:

```powershell
esptool --port COM7 flash-id                                     # confirm ESP32-S3
esptool --port COM7 read-flash 0x0 0x1000000 lv02_factory.bin    # back up NerdMiner first!
esptool --port COM7 erase-flash
esptool --port COM7 write-flash 0x0 ESP32_GENERIC_S3-*.bin
```

To restore the original miner: `esptool --port COM7 write-flash 0x0 lv02_factory.bin`. After
MicroPython is flashed the USB-CDC re-enumerates (PID 4001), usually as a new COM port.

> **The S3's USB-Serial/JTAG wedges frequently** with mpremote (especially on `reset`); recovery
> is a physical unplug/replug. The robust deploy is to install `main.py` then **power-cycle to
> autostart** — see `deploy.ps1 -Autostart` and the setup log.

## Deploy

```powershell
Copy-Item config.py.example config.py    # then edit: WiFi creds + server IP (not hostname)
pwsh deploy.ps1 -Port COM7               # copy lib + app + config
mpremote connect COM7 run _disptest.py   # display-only corner/orientation check (no WiFi)
pwsh deploy.ps1 -Port COM7 -Autostart    # install as main.py and reset (or power-cycle)
```

`config.py` and the 16 MB factory backup (`lv02_factory.bin`) are gitignored. The fonts
(`lib/dotmatrix19.py`) and `lib/writer.py` are shared with the CYD/NM-TV clients — regenerate via
`../cyd/tools/gen_fonts.ps1`.
