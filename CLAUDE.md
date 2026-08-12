# CLAUDE.md

Agent notes for RailInfo. The README is user-facing; this captures what isn't obvious from
the code, plus **where we are mid-task** (resume section at the bottom).

## Project

Software-only live National Rail departure board (LDBWS REST/JSON via Rail Data Marketplace).
Four phases: (1) terminal board, (2) Divoom Pixoo 64 push, (3) NAS container, (4) Heltec
e-ink client. **All four are done** — Phase 3 runs the merged server+Pixoo process as a
container on the Synology NAS (the live home; the dev box is just for local testing).

Data acquisition is decoupled from presentation behind `railinfo/domain` + `railinfo/service.py`
(`BoardService`). Renderers/servers depend only on the domain model.

## Architecture

- `railinfo/service.py` — `BoardService`: fetch + map LDBWS → domain. The seam everything wraps.
- `railinfo/renderers/pixoo.py` — 64×64 Pillow render (Phase 2), Dot Matrix TTF, thresholded.
- `railinfo/pixoo/` — Divoom device + hardened push `runner.py`. **`run(get_board, connect,
  fps)`** pulls the current board from a provider (the shared `BoardCache`) each frame and
  never fetches LDBWS itself; shows a "starting" placeholder until the first board lands. **The
  loop owns the whole device lifecycle**: it calls `connect()` (a factory; see
  `main._pixoo_connector`) *lazily* and reconnects via it after a run of failed pushes, so a
  Pixoo that's off at startup or vanishes mid-stream only makes it back off and retry — `run`
  never raises a `PixooError`. That keeps the JSON server (sibling thread) alive when the Pixoo
  is down.
- `railinfo/server.py` — **Phase 4 JSON API** (stdlib `http.server`). `python main.py --serve`.
  Views via `?view=`: `departures` (default, northbound, with calling points),
  `all` (every direction), `arrivals` (by origin). **`BoardCache`** holds the domain
  `DepartureBoard` per view (not JSON): **lazy on connect** (first request → `{"status":
  "starting"}` + background fetch; later polls get `"status":"ready"`), then
  **stale-while-revalidate** with coalesced refresh (one fetch in flight per view). `_project`
  renders each view's JSON; `make_server` builds the server headless so it can share a process
  + cache with the Pixoo loop (`--serve --pixoo --loop`) — one LDBWS fetch feeds both displays.
- `clients/heltec/` — **Phase 4 MicroPython client** for the Heltec Wireless Paper V1.2.

## Heltec client (`clients/heltec/`)

Polls `SERVER_URL?view=<view>` every ~5s and renders a board; e-ink full refresh (~1.5s) only
when the framebuffer actually changes (byte-compare). Modes cycled by the **PRG button (GPIO0)**:
`departures` (landscape) → `all departures` (portrait) → `arrivals` (portrait). A payload with
`status == "starting"` (the server's lazy first response) draws a **"Starting up..."** screen
instead of a board; the real board lands on a later poll.

- Fonts: **proportional** Dot Matrix bitmaps generated from `Fonts/dot-matrix-regular.ttf` —
  `dotmatrix9` (header/footer/portrait), `dotmatrix19` (landscape rows). Built by
  `tools/gen_fonts.ps1` = `font_to_py.py -x` (proportional) then `tools/tabular_digits.py`
  (centres narrow digits like "1" so numerals line up). **Only certain sizes render cleanly**
  (dot grid on whole pixels, even strokes): 8/9, 16/17, 19, 25/26/27, 34. 10–15, 18, 20–24,
  28–33 render broken/lopsided — avoid.
- Driver `lib/depg0213.py` — SSD1682, **vendored from the read-only ESP repo and refactored to
  subclass `framebuf.FrameBuffer`** (so Peter Hinch's `Writer` renders into it). Also whitens
  the off-panel pad strip (was a black bar at the top edge).
- Portrait = render into a 121×250 `PortraitCanvas`, transpose **90° CW** onto the 250×122
  panel (`_blit_portrait`). Width is 121 (not 122) to dodge a 1px clipped panel edge.
- Row layout: **Station (dest/origin) left; Platform + Time right-justified.** Status in the
  time: on-time = scheduled; delayed = `HH:MM :MM` (sched + revised minute); cancelled =
  `cancelled` right-justified. Header = station + clock; separator line under it.

## CYD client (`clients/cyd/`)

**Phase 4 hybrid client** for the **CYD / ESP32-2432S028** (original ESP32, **no PSRAM**; 2.8"
320×240 colour TFT + XPT2046 touch). **Display is an ILI9342, not ILI9341** — see [[cyd-h685-ili9342]]
and `clients/cyd/setup_log.md`. Same pull/multi-view model as the Heltec
(reuses `writer.py`, `font_to_py`/`tabular_digits`, `http_get_json`, the button-IRQ latch, the
`MODES` cycle, `_fit_px`/`_disp_time`), rendered in the **Pixoo's colour dot-matrix** look with
**per-row status colours** (amber on-time / orange delayed / red cancelled — `_status_colour`
mirrors `renderers/pixoo.py`). All three views are **landscape** (no portrait transpose).

- **Strip-blit renderer (no full framebuffer).** No PSRAM → a 320×240 RGB565 buffer (150 KB)
  won't fit. Each region (header / each row / footer) is drawn by `Writer` into a 1-bpp `Strip`
  (`framebuf.FrameBuffer`, MONO_HLSB), then `Board.blit_strip` expands lit pixels → the region's
  status colour (unlit → black) into a **reused** RGB565 scratch buffer and pushes it via the
  driver's `block()`. **Per-region change detection** (`Board._emit` caches mono bytes + colour)
  re-blits only changed regions, so a static board doesn't flicker; a full repaint (`clear()` +
  chrome + all regions) happens only on entry / view change (`force=True`).
- Fonts: **one clean size, dotmatrix19** (like the Heltec). On the sharp TFT the dot-matrix only
  rasterises crisply at ≤~19; bigger point sizes look off-grid. So the big departure rows are 19
  **integer-scaled ×2** at blit time (`BIG_SCALE`; `blit_strip(scale=…)` replicates each dot into
  a square block) — small text is 1×. `gen_fonts.ps1` uses `$sizes = @(19)`.
- Driver `lib/ili9341.py` — minimal, purpose-built (init + `block()`/`fill_rectangle()`/`clear()`
  only). **This unit is an ILI9342** (native 320×240 landscape): `ROTATION = 0x40` (MADCTL MX,
  **no MV** — MV half-widths it; no BGR — it's RGB). On **`SPI(1)`/HSPI @ 20 MHz** (SPI2 / 40 MHz
  failed). CS framed once per transaction; `block()` wants **big-endian** RGB565 (row-major with
  no MV). **Palette tuned for this green-heavy panel as rendered TEXT:** amber `(255,150,0)` /
  orange `(255,60,0)` / red `(255,0,0)` (the Pixoo's `(255,176,0)` reads green here).
- **Scrolling calling-at footer** (departures view): when wider than the screen the "Calling: …"
  line is drawn into a wide off-screen strip and slid ~50 px/s, animated by `board.tick_scroll`
  passed as `Inputs.wait(on_tick=…)` so it moves during the ~5s poll wait; short lists stay static.
- **Hybrid input — POLLED (`Inputs` class), not IRQ.** BOOT button by **GPIO0 level** + screen tap
  by **reading the XPT2046 pressure** (Z1) over SoftSPI (25/32/39, CS 33), both polled in the wait
  loop. **The touch IRQ line GPIO36 is unusable** (fires ~9 phantom IRQs/s; a real tap doesn't
  pull it low) — an IRQ design auto-cycled the view each poll and ate BOOT presses. Don't go back
  to IRQs on GPIO36.

## NM-TV client (`clients/nmtv/`)

**Fourth client** (added 2026-07-18): a repurposed **NMTech NM-TV-MINER v1.0** "SmallTV" desk
gadget (Sparkle XH-32S = plain ESP32, no PSRAM; **1.54" 240×240 ST7789 IPS**, 10-pin FPC).
A direct port of the CYD client (same strip-blit renderer, dotmatrix19 ×2 big rows, MODES
cycle, scrolling footer) with two deltas: 240px-wide geometry (vertical layout identical) and
**input = the case-top capacitive pad ("TC" → GPIO32, `machine.TouchPad`, startup-derived
threshold)** + BOOT poll. Verified pin map (docs half-wrong for v1.0 — see
`clients/nmtv/setup_log.md`, worth reading before touching ANY unknown display board):
SPI(1) mode 0 @20MHz SCK=14 MOSI=13 CS=15 DC=2, no RST; **backlight = GPIO19 (bl) + GPIO21
(pwr), BOTH ACTIVE LOW, driven low BEFORE panel init** — miss that and every draw is invisible
(this burned a full day chasing phantom pins; the "white flashes" during sweeps were backlight
blinks revealing stale panel RAM). `_probe_interactive.py`/`probe_one.py` = the interactive
pin-hunting tool that cracked it, kept for the next mystery board. **Backlight is PWM-dimmed**
(2026-07-31): the factory NMMiner firmware drives the backlight via LEDC/PWM (a "Brightness
0-100" setting — confirmed by dumping a fresh unit's firmware), so `boards.set_backlight` now
PWMs the active-low bl line (`BL_BRIGHTNESS`, default 90; 100 == pin held low == old full-on
DC). The old constant-DC drive made the backlight LED string glare as "obvious LEDs" at the
base of the panel; PWMing it fixed that with the panel reading about as bright. Factory NMMiner
dump = the restorable hardware-sanity anchor (kept OUT of the repo — licence keys + NVS WiFi;
unit 1 = v1.8.20 `nmminer_factory_backup.bin`, unit 2 = v1.8.26 `nmtv_unit2_factory_v1.8.26.bin`).

## LV02 client (`clients/lv02/`)

**Fifth client** (added 2026-08-01): a repurposed **Luckyminer LV02** BTC lottery-miner gadget
that is a **LilyGo T-Display-S3 CLONE** — **ESP32-S3, 16MB flash, NO PSRAM**, native USB-JTAG
(COM7). The 1.9" **170×320 ST7789** is on an **8-bit PARALLEL (i8080) bus, NOT SPI** — that was
the whole bring-up saga (full log in `clients/lv02/setup_log.md`; the memory note is the fast
read). Same pull/multi-view client as the NM-TV — it reuses the NM-TV `railinfo_client.py`
unchanged (single BOOT button GPIO0, `touch=None`); only `boards.py` + the parallel driver differ.

- Driver `lib/st7789.py` — a **parallel-i8080 ST7789** driver with the same tiny public API
  (`block`/`fill_rectangle`/`clear`/`color565`), so the strip-blit renderer is a drop-in. The data
  bus + WR strobe are driven via `machine.mem32` to the S3 GPIO registers and the hot pixel loops
  are `@micropython.viper` (full-screen push < ~1s). Verified pinout (= T-Display-S3): POWER_ON=15
  BL=38 CS=6 DC=7 RST=5 WR=8 RD=9; data D0..D7 = 39,40,41,42,45,46,47,48 (43/44 are UART0, skipped).
- **LANDSCAPE 320×170** (`landscape=True`; physical MADCTL `0xC0`, `glassw=170`). The driver
  presents 320×170 and rotates 90° onto the portrait glass: `_window` maps landscape (lx,ly) →
  physical (xp=glassw-1-ly, yp=lx) and `block()` streams via a transposing viper blit `_blit_t`
  (ST7789 RAMWR is column-fast, so a 320-wide strip can't go straight to CASET; MADCTL MV alone
  garbled the order). A native-portrait path is still in the driver if ever needed.
- **Vertical 1px offset / top-edge static (fixed 2026-08-12).** This glass is effectively **171
  visible columns**, not a clean 170, so the 170-wide content window always leaves one edge line
  out. `coloff=34` places content correctly (`[34..203]`) and avoids a bottom wrap, but the top
  physical column (`coloff+glassw`=204) is then never written → uninitialised RAM shows as
  multi-coloured static. Fix: `clear()` **blanks the porch line(s) to black** (`_blank_porch`,
  `porchpad=1`). **Don't chase this with `coloff` alone — it only swaps which edge breaks** (35 =
  bottom wrap, 34 = top static). Bump `porchpad` if a thin static line ever returns.
- **USB-Serial/JTAG WEDGES** constantly with mpremote (esp. on `reset`) — recovery is a physical
  unplug/replug. Robust flow: `mpremote cp … :main.py` then **power-cycle to autostart** (avoid
  `mpremote reset`). Deploy: `deploy.ps1 -Port COM7 [-Autostart]`; MicroPython ESP32_GENERIC_S3
  flashed at **`0x0`**. Factory NerdMiner V2 dump = `lv02_factory.bin` (gitignored — licence keys +
  NVS WiFi). `config.py` gitignored.

## Gotchas

- **The ESP repo `D:\Projects\ESP` is READ-ONLY** — copy out only, never modify. `depg0213.py`,
  WiFi/retry logic, board config, and `micropython_s3.bin` were copied from there.
- Heltec is on **COM3** (box-fresh ESP32-S3, MicroPython 1.28 flashed at `0x0`). Confirm S3.
- **CYD is on COM4** (CH340 USB-serial → **original ESP32, not S3**). MicroPython = generic
  `ESP32_GENERIC`, flashed at offset **`0x1000`** (NOT `0x0` — that's the S3). Confirm `flash-id`
  reports plain ESP32. `config.py` gitignored like the Heltec's.
- **A second CYD** (different manufacturer, same model) was flashed + deployed 2026-07-18 —
  enumerates as **COM5** (CH340), MAC `28:05:a5:2e:f3:30`, MicroPython 1.27.0 from
  `D:\Projects\ESP\micropython.bin`. Its panel **works with the unchanged ILI9342-tuned driver**
  (visually confirmed), device DHCP `192.168.1.147`. Same deploy flow: `deploy.ps1 -Port COM5`.
- **COM5 is shared**: the second CYD and the NM-TV both have CH340s and both enumerate as COM5
  (one attached at a time). Always `esptool flash-id` + eyeball which device is plugged in
  before flashing — the NM-TV and CYD flash the same way (ESP32_GENERIC @ `0x1000`) but run
  different clients.
- `mpremote` installed via `uv tool install mpremote`; `esptool` lives in `D:\Projects\ESP\.venv`.
- **Network ops need the sandbox disabled** (uv fetching freetype-py; the server's LDBWS calls).
  Serial (mpremote) and loopback curl do not.
- MicroPython can't resolve hostnames → `clients/heltec/config.py` `SERVER_URL` must be an IP.
  `config.py` is gitignored (WiFi creds + server IP). **Live: the NAS `192.168.1.10:8088`**
  (dev-box `192.168.1.116:8000` for local testing).
- Font regen needs freetype-py (cached in uv): `uv run --offline --with freetype-py ...`.
- Run tests: `uv run --offline pytest` (48 tests incl. `tests/test_server.py`).

## NAS deployment (Phase 3)

Live home: the merged process runs as the **`railinfo` container on the Synology NAS** (DS218+,
amd64) — `Dockerfile` (`python:3.14-slim`, uv, CMD `--serve --pixoo --loop --port 8000`) +
`docker-compose.yml` (`restart: unless-stopped`). Deploy with **`scripts/deploy-to-nas.ps1`**
(run on the dev box): `docker build` → `docker save` → `scp` → `docker load`; `-Start` also
writes a prebuilt-image compose + LF-normalised `.env` and runs compose up. Redeploy:
`pwsh scripts/deploy-to-nas.ps1 -NasHost <nas> -NasUser <admin> -SkipBuild -Start -HostPort 8088`.

- **Bridge + published port, NOT host networking.** `:8000` is taken by the user's `bindicator`
  container and `:8080` by `connect3`, so RailInfo publishes **`8088:8000`** (`-HostPort 8088`).
  Host mode isn't needed — PIXOO_HOST is pinned and bridge NAT reaches the Pixoo `.202` + LDBWS.
  Side effect: server logs show the bridge gateway `172.23.0.1` as the client IP, not the
  Heltec's real `192.168.1.139`.
- **Synology SSH/Docker quirks the script handles** (learned the hard way):
  - `scp -O` — Synology sshd has no SFTP subsystem ("subsystem request failed on channel 0").
  - `sudo` can't see `docker` (secure_path) → resolve the full path (`/usr/local/bin/docker`)
    and call `sudo <path>`. Same for compose.
  - Synology has **`docker-compose` v1 (hyphenated)**, not the `docker compose` v2 plugin —
    resolved separately (v1 first); the generated compose keeps `version: "3.8"` for v1.
  - `docker-compose down` before `up` (a failed recreate leaves the port "already allocated").
- **Pixoo PicID gotcha at cutover.** The panel silently drops frames whose `PicID` isn't greater
  than the last it saw (returns `error_code 0`, so **no push error is logged**). Two pushers at
  once (dev box + NAS during cutover) leave it stuck on the higher-numbered stream; **restart the
  surviving container** (`docker restart railinfo`) so its `Draw/ResetHttpGifId` re-syncs. Never
  run two Pixoo pushers at once.

---

## RESUME HERE — 2026-07-18

**All four phases done and live** (NAS container on `192.168.1.10:8088`; Heltec polls it).

### Done this session (2026-07-18, later) — NM-TV fourth client
- **Ported the CYD client to an NMTech NM-TV-MINER v1.0** ("SmallTV" ESP32 lottery-miner desk
  gadget, COM5) → `clients/nmtv/` — see the "NM-TV client" section above. Factory NMMiner
  v1.8.20 dumped (restorable; kept out of the repo), MicroPython ESP32_GENERIC flashed at
  `0x1000`. **The whole bring-up was a backlight trap**: the display data pins were the
  documented ones all along (CS=15 DC=2), but BOTH GPIO19+21 must be LOW (before init) for
  anything to be visible — full saga + lessons in `clients/nmtv/setup_log.md`. Touch pad =
  GPIO32 capacitive (found by TouchPad scan). **Live end-to-end + autostart confirmed**
  (device DHCP `192.168.1.206`, NAS board rendered, touch cycles views). Repo pruned to
  production files + `_probe_interactive.py`/`probe_one.py` (the reusable pin hunter).

### Done this session (2026-07-18)
- **README photo gallery**: `railinfoclients/` (Pixoo.jpeg / Heltec.jpeg / cyd.jpeg) added to
  the README intro. Photos were resized to 1600px and **EXIF-stripped (they carried GPS data)**
  before committing; untouched originals only in the (ephemeral) session scratchpad. Committed
  `0324537`, pushed.
- **Second CYD deployed** (different manufacturer, same ESP32-2432S028 model): COM5, flashed
  `ESP32_GENERIC` 1.27.0 at `0x1000`, deployed via `deploy.ps1 -Port COM5` (same client code +
  existing `config.py`), smoketest green (WiFi `192.168.1.147`, live NAS board), autostart
  installed. **Panel works with the unchanged ILI9342-tuned driver** — user visually confirmed;
  no code changes anywhere this deploy.

### Prior — 2026-07-01
This session added a **third client: the CYD colour-TFT client** (`clients/cyd/`) — see the
"CYD client" section above. Server unchanged; the Heltec is untouched.

### Done this session (2026-07-01) — new CYD (ESP32-2432S028) hybrid client
- **Goal**: a hybrid of the two existing clients — the Heltec's pull/multi-view behaviour in the
  Pixoo's colour dot-matrix look, on the CYD's 2.8" 320×240 ILI9341 colour TFT + XPT2046 touch.
  Toolchain **MicroPython** (max reuse of the Heltec pipeline). Device on **COM4** (CH340 →
  original ESP32, no PSRAM). No server changes — the three views already existed.
- **Built `clients/cyd/`** mirroring `clients/heltec/`: `railinfo_client.py` (main loop +
  `Board` strip-blit renderer), `boards.py` (SPI2 + ILI9341 + backlight), `lib/ili9341.py`
  (minimal purpose-built driver), copied `lib/writer.py`, generated `lib/dotmatrix17.py` +
  `dotmatrix27.py`, `tools/gen_fonts.ps1` (`$sizes = 17, 27`), `config.py.example`, `deploy.ps1`
  (COM4), `_smoketest.py`, `README.md`, `setup_log.md`. `.gitignore` now ignores
  `clients/cyd/config.py`. Root README + this file updated.
- **Rendering** (the crux): no PSRAM → no full RGB565 framebuffer; render each region into a
  1-bpp `Strip` via `Writer`, colourise (status colour) → RGB565 → `block()` (big rows ×2
  integer-scaled), with per-region change detection to avoid flicker. **Status by colour**
  (amber/orange/red). See "CYD client".
- **Hybrid input**: BOOT (GPIO0) + touch IRQ (GPIO36) both drive the same debounced press latch.
- **FLASHED, VERIFIED, and LIVE-DEPLOYED on-device 2026-07-01.** Long bring-up debug (see
  `clients/cyd/setup_log.md`): the panel (marked **H685**) is an **ILI9342 not ILI9341** → on
  `SPI(1)`/HSPI @ **20 MHz**, ROTATION **0x40 (no MV)**, RGB. Palette re-tuned for the green-heavy
  TFT. Font reworked to one clean **dotmatrix19** (big rows ×2 scaled). Departures + all/arrivals
  list + colours all confirmed correct on-panel. See [[cyd-h685-ili9342]].
- **Live and autostarting.** Real WiFi creds in `clients/cyd/config.py` (gitignored); smoketest
  confirmed WiFi (device DHCP `192.168.1.222`) + a live `ready` board fetched from the NAS
  (`192.168.1.10:8088`, station Earlswood, 4 services). Deployed as `:main.py` via
  `deploy.ps1 -Port COM4 -Autostart`; device reset and running the full poll/cycle loop.
- **Input reworked IRQ → polling (confirmed live).** The IRQ design auto-cycled every poll and
  ate BOOT presses (GPIO36 touch IRQ fires ~9 phantom edges/s; a real tap doesn't pull it low).
  Now polled: BOOT by GPIO0 level + tap by reading the XPT2046 pressure (SoftSPI). User confirmed
  BOOT/tap cycle views and no auto-cycling.
- **Scrolling calling-at footer added (confirmed live).** Long "Calling: …" lines scroll ~50 px/s;
  short ones stay static. See the "CYD client" section.
- **Fully working end-to-end on the live device, committed + pushed** (2026-07-01). `clients/cyd/`
  + the `.gitignore`/`README.md`/`CLAUDE.md` edits are in git; `config.py` stays gitignored. Any
  further work is optional polish (e.g. scroll speed via `FOOT_SCROLL_STEP`/`FOOT_SCROLL_MS`).

### Prior — 2026-06-25 — decouple the Pixoo from the JSON server
**All four phases done and live.** The merged server+Pixoo process runs as the `railinfo`
container on the **Synology NAS** (`192.168.1.10:8088`; see "NAS deployment" above); the Heltec
polls it and the dev-box processes are retired. The 2026-06-23 UI sign-off still holds.

### Done this session (2026-06-25) — decouple the Pixoo from the JSON server
- **Bug**: with the Pixoo powered off overnight (soak-testing the Heltec), the Heltec reported
  "Server error". Cause: in the merged process the Pixoo client was constructed *eagerly* on the
  main thread before/around the run loop (`PixooDevice.__init__` → `Draw/ResetHttpGifId`
  handshake). With the panel off that raised `PixooError` (`[Errno 113] No route to host`),
  `_run_combined` caught it, `return 1`, the `finally` tore the HTTP server down, the process
  exited — and `restart: unless-stopped` looped it. So the server (the Heltec's data source)
  flapped because the *Pixoo* was unreachable. The clients were not independent.
- **Fix — the run loop now owns the device lifecycle.** `runner.run(get_board, connect, fps)`
  (was `…, device, …`): it calls a **`connect` factory lazily**, treats a failed connect exactly
  like a failed push (back off, retry, never raise out of `run`), and reconnects via the same
  factory after `_RECONNECT_AFTER` push failures. `main._pixoo_connector(args, settings)` builds
  `connect` — it (re)resolves the host + constructs + sets brightness each call, so a Pixoo
  reboot re-applies brightness. `_run_combined` now **starts the HTTP server first and
  unconditionally** (no host gate, no eager device, no `except PixooError`); an absent Pixoo can
  no longer stop it. `--pixoo --loop` (standalone) routes through the connector too; the one-shot
  `--pixoo` push stays eager (report-and-exit is right for a single CLI command). Connect-outage
  logging is quiet: one WARNING when the panel goes away, INFO when it returns.
- **Tests**: signature updated; added `test_run_survives_pixoo_unreachable_at_startup` and
  `test_run_reconnects_via_connector_after_repeated_failures`. Suite **50 green** (`uv run
  --offline pytest`).
- **Deployed to the NAS, tested, committed + pushed.** Verified the decoupling live (Pixoo off →
  the Heltec/JSON server stays up; the Pixoo reconnects on its own when powered back on).
- **Closed out the last two pending items.** Repo-side font cleanup was already complete (a prior
  session did it but never cleared the note): `clients/heltec/lib/` holds only `dotmatrix9/19`
  + `writer`/`depg0213`, no `dm*mono`/extra sizes anywhere, and `gen_fonts.ps1` is already
  `9, 19`. Reviewed `setup_log.md` — the esptool/flash flow is current; added one line clarifying
  the live server is the NAS (the dev-box IP in §5 was bring-up only).

### Done this session (2026-06-24)
- **PRG button fix** (symptom: it only seemed to act when the board data changed). Cause: the
  button was only *polled* inside the 5s wait, so presses during the blocking socket fetch or
  the ~1.5s e-ink refresh were dropped; the on-device `main.py` was also stale. Now a **Pin IRQ**
  (`IRQ_FALLING`, 300ms time-debounce) latches the press; the loop consumes it at the top and
  advances the view with `force=True`, refreshing **regardless of data**. `_wait` returns early
  on the latch. Validated on-device (cycles departures→all→arrivals within ~5s on a static board).
- **Installed as autostart** — `railinfo_client.py` cp'd to `:main.py` (byte-match, 12880 B);
  stale copy removed.
- **Device pruned** to production-only: root `boot/main/config/boards.py` + `lib/{depg0213,
  writer,dotmatrix9,dotmatrix19}`. Removed the scratch scripts, the stale `railinfo_client.py`,
  and font leftovers `dotmatrix16/17/20..30` — all still in the repo, re-deployable.
- **Pixoo delay notation now matches the Heltec** — `pixoo.py:_headline_time` renders
  `HH:MM :MM` (sched + revised minute) instead of replacing the time. Test updated; full suite
  **38 green**; live stream restarted onto the new code.

### Done this session (2026-06-24, cont.)
- **Pixoo: station code never truncated** (part a). `_draw_departure` used to draw the right
  block first then truncate the code to fit; inverted it. New `_choose_layout` reserves the full
  code + `<` marker and picks the richest right block that fits beside it via `_right_candidates`
  (full `P# HH:MM[ :MM]` → drop platform → drop `:MM`). A long destination *name* (never a CRS)
  can still be trimmed as a last resort. Tests: `test_marked_delayed_keeps_full_code` etc.
- **Server lazy on connect** (part b). Dropped the startup prime in `serve()`; `ViewCache` now
  starts empty and, on the first request per view, returns `{"status":"starting"}` and runs the
  initial `_fetch` on a daemon thread (guarded by `_inflight`; logs "First client connected…").
  Real board (`"status":"ready"`) lands on a later poll. `/board` is now always 200 (no more
  503 "no board yet"). `to_client_dict` gained `"status":"ready"`. `--serve` help reworded.
- **Heltec shows "Starting up..."** on `status == "starting"` (`railinfo_client.py`, new
  `_draw_status`). **Repo only — NOT yet redeployed to the device** (still runs the prior
  autostart `main.py`; un-redeployed it degrades to a blank "No departures" frame for ~1 poll).
- **Docs**: README gained a real **Phase 4** section + the run-both-displays commands; fixed the
  stale Pixoo delay notation. CLAUDE.md architecture/decisions updated. Suite **45 green**.

### Done this session (2026-06-24 — server merge)
- **Merged the JSON server and the Pixoo loop into one process** to halve LDBWS calls: the
  `departures` board was being fetched twice — once by `--serve` for the Heltec, once by the
  Pixoo `--loop`, identically. Now `main.py --serve --pixoo --loop` runs both sharing one
  `BoardCache`. `_run_combined` runs the HTTP server in a daemon thread + the Pixoo loop on the
  main thread (which owns SIGTERM via `runner._stop_requested`); Ctrl-C/SIGTERM stop both.
- **`ViewCache` → `BoardCache`**: caches domain `DepartureBoard`s (not JSON) via `get_board`;
  **stale-while-revalidate** + coalesced background refresh (`_inflight`) so the ~5fps Pixoo
  poll can't fan out into duplicate fetches, and neither consumer blocks. Projection moved to
  `_project(view, board)`; `make_server` factored out of `serve`.
- **`runner.run(get_board, device, fps)`** replaced `run(service, …, refresh, board_kwargs)`;
  pulls the cached board each frame, shows `render_starting_image()` (new in `pixoo.py`) until
  the first board lands. Pixoo-only `--loop` routes through a `BoardCache` too.
- **Heltec JSON contract unchanged** — no device re-deploy needed. `Dockerfile` CMD (was the
  stale `--loop`) + `docker-compose.yml` collapsed to one combined service (split kept as a
  commented alt). Suite **48 green**.

### Done this session (2026-06-24 — Phase 3 NAS deploy + cutover)
- **Built + smoke-tested the image** (`railinfo:latest`, linux/amd64): in-container render path,
  `/healthz`, and `/board` lazy-start all green.
- **Wrote `scripts/deploy-to-nas.ps1`** (build → save → scp → load over SSH; `-Start` brings it
  up via compose). Iterated through the Synology quirks now captured in "NAS deployment":
  `scp -O`, full-path `sudo docker`, `docker-compose` v1, bridge `-HostPort`, `down` before `up`.
- **Deployed to the NAS** as the `railinfo` container on **`8088`** (`:8000`=bindicator,
  `:8080`=connect3 were taken). Verified `/healthz` + a real `ready` board from the NAS.
- **Cut over**: Heltec `config.py` SERVER_URL → `http://192.168.1.10:8088/board` (cp'd to the
  device, sha-matched, reset); **stopped the dev-box process**. Restarted the NAS container once
  to clear a Pixoo PicID stall from the dual-push overlap. Both displays live off the NAS.

### Run it
**Live = the NAS container** (`scripts/deploy-to-nas.ps1`; see "NAS deployment"). The Heltec
polls `192.168.1.10:8088`; device DHCP `192.168.1.139`.

**Local testing on the dev box** (network → **disable sandbox**; point the Heltec's config.py
back at `192.168.1.116:8000`, or just curl /board yourself):
`uv run python -u main.py --serve --pixoo --loop --port 8000` — one process feeds both displays
from a single LDBWS fetch. (Split mode `--serve` + `--pixoo --loop` still works but doubles the
departures fetch; dev-box processes die when the box sleeps — the NAS doesn't.)

### Still pending
- _(none — all caught up.)_

### Decisions locked
- Proportional fonts (NOT monospaced); 9 + 19 only; tabular/centred digits.
- Delay notation `HH:MM :MM` on **both** Heltec and Pixoo; `cancelled` (lowercase) right-justified.
- Direction filter `DIRECTION_FILTER_CRS=RDH` in `.env` drives the default **northbound** view
  (changed from LBG 2026-07-19: filtering on London Bridge silently dropped London Victoria
  services. Every northbound/Platform-1 train from Earlswood calls at Redhill next — including
  all Victoria and London Bridge trains — and no southbound train does, so RDH ≡ northbound
  and needs no code change; the LDBWS `filterCrs` still does the work server-side).
- PRG=GPIO0 via **Pin IRQ** (not polling); portrait transpose 90° CW; PortraitCanvas 121×250.
- Pixoo rows mirror the Heltec's right block (`P# HH:MM`), drawn **flush-right** (`SIZE + 1`
  absorbs the font side-bearing). **The station code is never truncated**: the right block
  degrades to fit beside the whole code + `<` marker — `P# HH:MM[ :MM]` → drop `P` (delayed) →
  drop platform → drop `:MM`. (`_choose_layout` / `_right_candidates` in `pixoo.py`.)
- Server is **lazy on connect** (no LDBWS at startup); first request per view → `status:
  "starting"` + background fetch. Clients render "starting" as a notice, not an error.
- **Server + Pixoo run as ONE process** sharing a `BoardCache` (`--serve --pixoo --loop`) — the
  `departures` board is fetched from LDBWS once for both displays. The cache stores domain
  boards (stale-while-revalidate + coalesced refresh). The Pixoo reads the shared board object
  directly (NOT an HTTP client of `/board`); the JSON contract stays the Heltec's alone. Split
  mode (two processes) still works but doubles the departures fetch.
- **Phase 3 = that one process as the `railinfo` container on the Synology NAS** (the live home).
  **Bridge networking + `-HostPort 8088`** publish (NOT host mode; `:8000`/`:8080` are taken by
  the user's bindicator/connect3). Deploy via `scripts/deploy-to-nas.ps1`. Never run two Pixoo
  pushers at once (PicID stall) — see "NAS deployment".
- **The two clients are independent.** A down/unreachable Pixoo must NEVER stop the JSON server
  (the Heltec's data source). The merged process starts the server first + unconditionally; the
  Pixoo run loop connects lazily and retries forever via a `connect` factory, never raising out
  of `runner.run`. (Likewise the server is lazy on connect, so the Heltec doesn't depend on the
  Pixoo for the first fetch.) Don't reintroduce eager Pixoo construction on the main thread.
