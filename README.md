# RailInfo

A software-only live National Rail departure board, inspired by
[chrisys/train-departure-display](https://github.com/chrisys/train-departure-display)
but with no Raspberry Pi hardware. It reads real-time data from the National Rail
**LDBWS** REST API (via the Rail Data Marketplace) and renders it to the terminal or a
[Divoom Pixoo 64](https://divoom.com/products/pixoo-64).

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
- **Delayed services show their revised expected time** (e.g. `13:59`), not the scheduled one.
- **The "calling at…" line follows the first non-cancelled departure** with stops; if that
  isn't the top row, a `<` after its CRS code marks which train it belongs to.
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

Data acquisition is decoupled from presentation behind a stable domain model, so a future
containerised service (Phase 3) and ESP32 e-ink client (Phase 4) can share the same
contract:

- `railinfo/config.py` — load `.env` into per-product endpoints.
- `railinfo/ldbws/client.py` — thin HTTP client (URL templating, `x-apikey`, errors).
- `railinfo/domain/` — `models.py` (the contract) and `mapper.py` (LDBWS JSON → model).
- `railinfo/service.py` — fetch + map; the seam a Phase 3 HTTP API would wrap.
- `railinfo/renderers/` — consume the domain model only (`terminal.py`, `pixoo.py`).
- `railinfo/pixoo/` — `device.py` (Divoom HTTP API + LAN discovery) and `runner.py` (loop).
- `tests/` — pytest suite; `scripts/preview_board.py` — offline PNG preview.

## Roadmap

- **Phase 3** (optional) — containerise the service for a Synology NAS.
- **Phase 4** (optional) — ESP32 e-ink client consuming the same JSON.

## Credits

- Dot-matrix typeface: **Dot Matrix** by Daniel Hart
  ([DanielHartUK/Dot-Matrix-Typeface](https://github.com/DanielHartUK/Dot-Matrix-Typeface)),
  used under the SIL Open Font License.
- Divoom HTTP protocol reference: [SomethingWithComputers/pixoo](https://github.com/SomethingWithComputers/pixoo) /
  [4ch1m/pixoo-rest](https://github.com/4ch1m/pixoo-rest) (used as references for the
  command set; not runtime dependencies)
