"""Shared test helpers."""

from __future__ import annotations

from railinfo.domain.models import CallingPoint, Service


def make_service(
    *,
    std: str | None = "13:25",
    etd: str | None = "On time",
    sta: str | None = None,
    eta: str | None = None,
    platform: str | None = "1",
    destination: str | None = "Peterborough",
    destination_crs: str | None = "PBO",
    origin: str | None = "Horsham",
    via: str | None = None,
    operator: str | None = "Thameslink",
    is_cancelled: bool = False,
    calling_points: list[CallingPoint] | None = None,
) -> Service:
    """Build a Service with sensible defaults; override only what a test cares about."""
    return Service(
        std=std, etd=etd, sta=sta, eta=eta, platform=platform,
        destination=destination, destination_crs=destination_crs, origin=origin,
        via=via, operator=operator, is_cancelled=is_cancelled,
        calling_points=calling_points or [],
    )
