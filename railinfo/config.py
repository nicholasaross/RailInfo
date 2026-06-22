"""Configuration loaded from the environment / .env file.

The Rail Data Marketplace exposes each LDBWS product at its own base URL and with its
own ``x-apikey`` consumer key. We model each product as an :class:`Endpoint` (a URL
template plus its key) so the rest of the app can stay agnostic about which operation it
is calling. Keeping this seam clean is what lets a future containerised service (Phase 3)
serve the same data without touching the client or domain code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Logical endpoint name -> the suffix used on the matching .env variables.
_ENDPOINT_SUFFIXES = {
    "ldb": "LDB",  # Live Departure Board (primary)
    "ladb": "LADB",  # Live Arrival and Departure Boards (with calling points)
    "lndb": "LNDB",  # Live Next Departures Board (filtered)
    "sd": "SD",  # Service Details (calling points for one serviceID)
}

DEFAULT_FILTER_CRS = ["LBG", "VIC", "RDH"]


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


@dataclass(frozen=True)
class Endpoint:
    """A single LDBWS product: a URL template and the key that unlocks it."""

    name: str
    url_template: str
    api_key: str


@dataclass(frozen=True)
class Settings:
    endpoints: dict[str, Endpoint]
    station_crs: str
    filter_crs_list: list[str] = field(default_factory=lambda: list(DEFAULT_FILTER_CRS))
    time_offset: int = 0
    time_window: int = 120
    pixoo_host: str | None = None  # optional; auto-discovered if unset
    # Directional filter for the standard departure board: show only services that call
    # at this CRS (e.g. LBG for London-bound trains). ``direction_filter_type`` is "to"
    # (calls at, after here) or "from" (came via, before here). None = no filter.
    direction_filter_crs: str | None = None
    direction_filter_type: str = "to"

    def endpoint(self, name: str) -> Endpoint:
        try:
            return self.endpoints[name]
        except KeyError:
            raise ConfigError(
                f"No endpoint configured for '{name}'. Set LDBWS_BASE_URL_"
                f"{_ENDPOINT_SUFFIXES.get(name, name.upper())} and BWS_API_KEY_"
                f"{_ENDPOINT_SUFFIXES.get(name, name.upper())} in .env."
            ) from None


def load_settings() -> Settings:
    """Build :class:`Settings` from the environment (loading .env first)."""

    load_dotenv()

    endpoints: dict[str, Endpoint] = {}
    for name, suffix in _ENDPOINT_SUFFIXES.items():
        url = os.environ.get(f"LDBWS_BASE_URL_{suffix}")
        key = os.environ.get(f"BWS_API_KEY_{suffix}")
        if url and key:
            endpoints[name] = Endpoint(name=name, url_template=url, api_key=key)

    if "ldb" not in endpoints:
        raise ConfigError(
            "The primary departure board is not configured. Set LDBWS_BASE_URL_LDB "
            "and BWS_API_KEY_LDB in .env."
        )

    station_crs = os.environ.get("STATION_CRS", "").strip().strip('"').upper()
    if not station_crs:
        raise ConfigError("STATION_CRS is not set in .env.")

    raw_filter = os.environ.get("FILTER_CRS_LIST", "").strip().strip('"')
    filter_crs_list = (
        [c.strip().upper() for c in raw_filter.split(",") if c.strip()]
        if raw_filter
        else list(DEFAULT_FILTER_CRS)
    )

    direction_crs = os.environ.get("DIRECTION_FILTER_CRS", "").strip().strip('"').upper()
    direction_type = (
        os.environ.get("DIRECTION_FILTER_TYPE", "to").strip().strip('"').lower() or "to"
    )

    return Settings(
        endpoints=endpoints,
        station_crs=station_crs,
        filter_crs_list=filter_crs_list,
        time_offset=int(os.environ.get("LDBWS_TIME_OFFSET", "0")),
        time_window=int(os.environ.get("LDBWS_TIME_WINDOW", "120")),
        pixoo_host=(os.environ.get("PIXOO_HOST", "").strip().strip('"') or None),
        direction_filter_crs=direction_crs or None,
        direction_filter_type=direction_type,
    )
