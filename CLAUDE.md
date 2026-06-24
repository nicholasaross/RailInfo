# CLAUDE.md

Agent notes for RailInfo. The README is user-facing; this captures what isn't obvious from
the code, plus **where we are mid-task** (resume section at the bottom).

## Project

Software-only live National Rail departure board (LDBWS REST/JSON via Rail Data Marketplace).
Four phases: (1) terminal board, (2) Divoom Pixoo 64 push, (3) NAS container, (4) Heltec
e-ink client. Phases 1, 2, 4 are done; Phase 3 (NAS deploy) is deferred.

Data acquisition is decoupled from presentation behind `railinfo/domain` + `railinfo/service.py`
(`BoardService`). Renderers/servers depend only on the domain model.

## Architecture

- `railinfo/service.py` — `BoardService`: fetch + map LDBWS → domain. The seam everything wraps.
- `railinfo/renderers/pixoo.py` — 64×64 Pillow render (Phase 2), Dot Matrix TTF, thresholded.
- `railinfo/pixoo/` — Divoom device + hardened push `runner.py`. **`run(get_board, device,
  fps)`** pulls the current board from a provider (the shared `BoardCache`) each frame and
  never fetches LDBWS itself; shows a "starting" placeholder until the first board lands.
- `railinfo/server.py` — **Phase 4 JSON API** (stdlib `http.server`). `python main.py --serve`.
  Views via `?view=`: `departures` (default, London-bound, with calling points),
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

## Gotchas

- **The ESP repo `D:\Projects\ESP` is READ-ONLY** — copy out only, never modify. `depg0213.py`,
  WiFi/retry logic, board config, and `micropython_s3.bin` were copied from there.
- Heltec is on **COM3** (box-fresh ESP32-S3, MicroPython 1.28 flashed at `0x0`). Confirm S3.
- `mpremote` installed via `uv tool install mpremote`; `esptool` lives in `D:\Projects\ESP\.venv`.
- **Network ops need the sandbox disabled** (uv fetching freetype-py; the server's LDBWS calls).
  Serial (mpremote) and loopback curl do not.
- MicroPython can't resolve hostnames → `clients/heltec/config.py` `SERVER_URL` must be an IP.
  `config.py` is gitignored (WiFi creds + server IP); dev-box server = `192.168.1.116:8000`.
- Font regen needs freetype-py (cached in uv): `uv run --offline --with freetype-py ...`.
- Run tests: `uv run --offline pytest` (45 tests incl. `tests/test_server.py`).

---

## RESUME HERE — 2026-06-24

Phase 4 done + polished live. The Heltec runs the fixed client as **autostart `main.py`**;
sign-off received on the 2026-06-23 UI batch (row order Station/Platform/Time, "cancelled"
right-justified, portrait edge-clip fix, header separator). Server + Pixoo stream are dev-box
processes (ephemeral — see below).

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

### Run it (dev box — dies if the box sleeps or Claude/terminal closes; auto-restart wrapper helps)
ONE process now feeds both displays, sharing a single LDBWS fetch (network → **disable sandbox**):
1. `uv run python -u main.py --serve --pixoo --loop --port 8000` (Pixoo auto-discovers .202;
   serves /board on :8000 for the Heltec). Idle on the LDBWS side until something displays it.
2. Heltec autostarts on power; recovers ~5s after the server returns. config.py →
   `192.168.1.116:8000`; device DHCP `192.168.1.139`. (Re-check dev-box IP with `ipconfig`.)
   (Split mode still works — `--serve` and `--pixoo --loop` as two processes — but doubles the
   departures fetch.)

### Still pending
- [ ] **Redeploy the Heltec** to pick up the "Starting up..." screen: `mpremote` cp
      `railinfo_client.py` → `:main.py` on COM3 (byte-match + remove stale). Optional — the
      device works without it; it just won't show the startup notice. Validate the lazy-server
      startup flow on-device after.
- [ ] **Repo-side** font cleanup (device is done): delete `clients/heltec/lib/`
      `dotmatrix16/17/18/20..30` + `dm16mono/dm18mono/dm19mono`; set `gen_fonts.ps1 $sizes` to
      `9, 19`. (Repo keeps the scratch scripts as source/diagnostics.)
- [ ] Update `clients/heltec/README.md` + `setup_log.md` (proportional 9/19 fonts, row layout,
      `HH:MM :MM` notation, PRG **IRQ** modes/portrait, the gen_fonts+tabular_digits flow).
- [ ] Phase 3 NAS deploy of `railinfo-server` + the Pixoo loop (the permanent home for both
      dev-box processes) — still deferred.

### Decisions locked
- Proportional fonts (NOT monospaced); 9 + 19 only; tabular/centred digits.
- Delay notation `HH:MM :MM` on **both** Heltec and Pixoo; `cancelled` (lowercase) right-justified.
- Direction filter `DIRECTION_FILTER_CRS=LBG` in `.env` drives the default London-bound view.
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
