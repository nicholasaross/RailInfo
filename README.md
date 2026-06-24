# RailInfo

A software-only live National Rail departure board, inspired by
[chrisys/train-departure-display](https://github.com/chrisys/train-departure-display)
but with no Raspberry Pi hardware. It reads real-time data from the National Rail
**LDBWS** REST API (via the Rail Data Marketplace) and renders it to the terminal, a
[Divoom Pixoo 64](https://divoom.com/products/pixoo-64), or a battery e-ink board (a
Heltec Wireless Paper) fed by a small JSON server.

## Phase 1 — LDBWS departure board (done)

Fetches a station's live board and prints it to the terminal.

```bash
uv sync
uv run python main.py            # departure board for STATION_CRS
uv run python main.py --details  # + calling points (via Service Details, one call/service)
uv run python main.py --arrdep   # arrivals + departures, with calling points
uv run python main.py --next     # next train to each FILTER_CRS_LIST destination
uv run python main.py --crs PAD  # any station by CRS code
uv run python main.py --json     # the normalised domain model as JSON
```

#### Filtering by direction

The standard departure board can be restricted to trains heading a particular way, which
LDBWS does server-side by matching a station the service *calls at* (not just its
terminus — handy when London-bound trains run *through* London rather than ending there):

```bash
uv run python main.py --to LBG          # only services calling at London Bridge
uv run python main.py --from GTW         # only services that called at Gatwick before here
uv run python main.py --all-directions   # ignore the DIRECTION_FILTER_CRS default
```

Set `DIRECTION_FILTER_CRS` in `.env` (see below) to make this the default for every board
(terminal, `--pixoo`, and `--loop`); the flags above override it per run. The directional
filter applies to the standard board only — `--next` and `--arrdep` use their own endpoints.

### Configuration (`.env`)

Each Rail Data Marketplace product has its own base URL and `x-apikey` consumer key:

```
BWS_API_KEY_LDB   / LDBWS_BASE_URL_LDB     # Live Departure Board (primary)
BWS_API_KEY_LADB  / LDBWS_BASE_URL_LADB    # Live Arrival and Departure Boards (calling points)
BWS_API_KEY_LNDB  / LDBWS_BASE_URL_LNDB    # Live Next Departures Board (filtered)
BWS_API_KEY_SD    / LDBWS_BASE_URL_SD      # Service Details (calling points for one serviceID)
STATION_CRS="ELD"                          # default station (Earlswood, Surrey)
FILTER_CRS_LIST="LBG,VIC,RDH"              # optional; destinations for --next
DIRECTION_FILTER_CRS="LBG"                 # optional; default direction filter (e.g. London-bound)
DIRECTION_FILTER_TYPE="to"                 # "to" (calls here after) or "from" (came via here)
```

URLs are templates containing `{crs}` (or `{filterList}` for next-departures, `{serviceid}`
for service details). The `_LDB` product is `GetDepartureBoard`, which has no calling
points; get the "calling at…" line either with `--details` (enriches each service via the
`_SD` Service Details product) or with `--arrdep` (the Arrival/Departure board already
includes them in a single call).

## Phase 2 — Pixoo 64 display (done)

Renders the board to a [Divoom Pixoo 64](https://divoom.com/products/pixoo-64) in the
National Rail dot-matrix font (amber on black): three departures shown as
**destination CRS code + time** (codes keep the font large and legible on the 64px panel),
a scrolling "calling at…" line, and a large clock. Details:

- **Colour encodes status** — amber = on time, orange = delayed, red = cancelled.
- **Delayed services show the scheduled time plus the revised minute** (e.g. `13:25 :28`),
  matching the e-ink board's notation; the `P` platform prefix is dropped to make room.
- **The "calling at…" line follows the first non-cancelled departure** with stops; if that
  isn't the top row, a `<` after its CRS code marks which train it belongs to. The station
  code is **never truncated** — when room is tight the platform/minute give way instead.
- **Glyphs are thresholded to pure on/off pixels** after rendering, so the TrueType font's
  antialiasing fringe never reaches the LEDs — it stays crisp at this size.

```bash
uv run python main.py --preview out.png   # save a 64x64 PNG (no device needed)
uv run python main.py --pixoo             # push one frame to the Pixoo
uv run python main.py --pixoo --loop      # stream: scroll + refresh until Ctrl+C
uv run python main.py --pixoo --brightness 80
```

The Pixoo talks over **Wi-Fi** (USB is power only) on port 80. The device IP is found
automatically via Divoom's LAN discovery; override with `--pixoo-host` or `PIXOO_HOST` in
`.env`. Frames are pushed over HTTP (`Draw/SendHttpGif`), which caps at ~5 fps, so the
scroll is deliberately paced. `--loop` re-fetches data every `--interval` seconds (default
30) and keeps the last good board if a refresh fails.

## Phase 4 — JSON server + Heltec e-ink client (done)

A small stdlib HTTP server (`--serve`) exposes the board as JSON at `/board`, and a
[Heltec Wireless Paper](clients/heltec/README.md) (ESP32-S3 + 2.13" e-ink, MicroPython)
polls it over Wi-Fi and renders a live board. Three views, chosen with `?view=`:

- `departures` (default) — London-bound board with the "calling at…" line (landscape).
- `all` — every departure, no direction filter (portrait).
- `arrivals` — arriving services, labelled by origin (portrait).

The server **holds no state until a client connects** — it never calls LDBWS at startup.
The first request for a view returns `{"status": "starting", …}` immediately and fetches
that view in the background; once it lands, later polls get the real board (`"status":
"ready"`). Each view is then cached and refreshed lazily (per-view TTL = `--interval`,
default 30s), keeping the last good board if a refresh fails. So the server sits idle — and
makes no API calls — whenever nothing is displaying it.

### Run both displays

One process serves the Heltec's JSON API **and** streams to the Pixoo, sharing a single board
cache — so the London-bound board is fetched from LDBWS **once** and used by both, instead of
each display fetching it independently:

```bash
uv run python -u main.py --serve --pixoo --loop --port 8000
```

`--interval` sets the shared cache TTL (default 30s); `--fps` the Pixoo scroll rate. You can
still run either side alone — `--serve` (API only) or `--pixoo --loop` (Pixoo only) — but
together in one process is what avoids the duplicate upstream fetch.

The Heltec can't resolve hostnames, so set the server's LAN IP (not a name) in
`clients/heltec/config.py`. See the [client README](clients/heltec/README.md) for flashing,
fonts, the PRG-button view cycling, and configuration.

## Development

```bash
uv run pytest                                  # run the test suite (network-free)
uv run python -m scripts.preview_board --scale 10   # render a sample board to preview.png
```

Tests live in `tests/` and cover the pure logic — LDBWS-JSON mapping, the directional
filter resolution, and the Pixoo renderer's status/time/stop-selection helpers — using
fixtures rather than live API calls. `scripts/preview_board.py` renders a representative
board (on-time / delayed / cancelled services) straight to a PNG with no device or network
needed, which is the quickest way to eyeball a rendering change.

## Architecture

Data acquisition is decoupled from presentation behind a stable domain model, so every
renderer — terminal, Pixoo, and the e-ink client's JSON server — shares one contract:

- `railinfo/config.py` — load `.env` into per-product endpoints.
- `railinfo/ldbws/client.py` — thin HTTP client (URL templating, `x-apikey`, errors).
- `railinfo/domain/` — `models.py` (the contract) and `mapper.py` (LDBWS JSON → model).
- `railinfo/service.py` — fetch + map; the seam every renderer and the server wrap.
- `railinfo/renderers/` — consume the domain model only (`terminal.py`, `pixoo.py`).
- `railinfo/pixoo/` — `device.py` (Divoom HTTP API + LAN discovery) and `runner.py` (loop).
- `railinfo/server.py` — Phase 4 JSON API (`--serve`); projects the domain model to `/board`.
- `clients/heltec/` — MicroPython e-ink client (polls the server; see its own README).
- `tests/` — pytest suite; `scripts/preview_board.py` — offline PNG preview.

## Roadmap

- **Phase 3** (deferred) — containerise the service + Pixoo loop for a Synology NAS, the
  permanent home for the two dev-box processes. A `docker-compose.yml` with both services
  (`railinfo-server` and the Pixoo `--loop`) is already in the repo.

## Credits

- Dot-matrix typeface: **Dot Matrix** by Daniel Hart
  ([DanielHartUK/Dot-Matrix-Typeface](https://github.com/DanielHartUK/Dot-Matrix-Typeface)),
  used under the SIL Open Font License.
- Divoom HTTP protocol reference: [SomethingWithComputers/pixoo](https://github.com/SomethingWithComputers/pixoo) /
  [4ch1m/pixoo-rest](https://github.com/4ch1m/pixoo-rest) (used as references for the
  command set; not runtime dependencies)
