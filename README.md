# RailInfo

A software-only live National Rail departure board, inspired by
[chrisys/train-departure-display](https://github.com/chrisys/train-departure-display)
but with no Raspberry Pi hardware. It reads real-time data from the National Rail
**LDBWS** REST API (via the Rail Data Marketplace) and will ultimately render to a
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

### Configuration (`.env`)

Each Rail Data Marketplace product has its own base URL and `x-apikey` consumer key:

```
BWS_API_KEY_LDB   / LDBWS_BASE_URL_LDB     # Live Departure Board (primary)
BWS_API_KEY_LADB  / LDBWS_BASE_URL_LADB    # Live Arrival and Departure Boards (calling points)
BWS_API_KEY_LNDB  / LDBWS_BASE_URL_LNDB    # Live Next Departures Board (filtered)
BWS_API_KEY_SD    / LDBWS_BASE_URL_SD      # Service Details (calling points for one serviceID)
STATION_CRS="ELD"                          # default station (Earlswood, Surrey)
FILTER_CRS_LIST="LBG,VIC,RDH"              # optional; destinations for --next
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
a scrolling "calling at…" line, and a clock. Colour encodes status (amber = on time,
orange = delayed, red = cancelled).

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

## Roadmap

- **Phase 3** (optional) — containerise the service for a Synology NAS.
- **Phase 4** (optional) — ESP32 e-ink client consuming the same JSON.

## Credits

- Dot-matrix typeface: [DanielHartUK/Dot-Matrix-Typeface](https://github.com/DanielHartUK/Dot-Matrix-Typeface)
- Pixoo control: [4ch1m/pixoo-rest](https://github.com/4ch1m/pixoo-rest) /
  [SomethingWithComputers/pixoo](https://github.com/SomethingWithComputers/pixoo)
