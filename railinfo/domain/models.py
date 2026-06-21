"""The internal domain model — the stable contract shared by every renderer.

This is intentionally decoupled from the LDBWS JSON schema. Renderers (terminal, Pixoo)
and any future service boundary (Phase 3 HTTP API, Phase 4 ESP32 client) depend on these
dataclasses, never on the raw API payload. Keep them small and serialisable.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CallingPoint:
    location: str
    crs: str | None = None  # 3-letter station code
    st: str | None = None  # scheduled time at this point
    et: str | None = None  # estimated time (if no actual)
    at: str | None = None  # actual time (if known)


@dataclass(frozen=True)
class Service:
    std: str | None  # scheduled departure
    etd: str | None  # expected departure ("On time"/"Cancelled"/"HH:MM")
    sta: str | None  # scheduled arrival
    eta: str | None  # expected arrival
    platform: str | None
    destination: str | None
    destination_crs: str | None
    origin: str | None
    via: str | None
    operator: str | None
    is_cancelled: bool = False
    cancel_reason: str | None = None
    delay_reason: str | None = None
    calling_points: list[CallingPoint] = field(default_factory=list)
    service_id: str | None = None  # used to fetch calling points via GetServiceDetails

    @property
    def time(self) -> str:
        """The headline scheduled time (departure if present, else arrival)."""
        return self.std or self.sta or "—"

    @property
    def expected(self) -> str:
        """Human-readable status: the estimate, or 'Cancelled'."""
        if self.is_cancelled:
            return "Cancelled"
        return self.etd or self.eta or "On time"


@dataclass(frozen=True)
class DepartureBoard:
    location_name: str | None
    crs: str | None
    generated_at: str | None
    nrcc_messages: list[str] = field(default_factory=list)
    services: list[Service] = field(default_factory=list)
