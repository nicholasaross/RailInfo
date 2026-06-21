"""Map raw LDBWS JSON into the internal :mod:`railinfo.domain.models`.

One entry point, :func:`from_ldbws`, handles every operation we use:

* ``StationBoard`` / ``StationBoardWithDetails`` (GetDepartureBoard,
  GetArrDepBoardWithDetails, …) — services live under ``trainServices``.
* ``DeparturesBoard`` (GetNextDepartures) — services live under ``departures[].service``.

The "WithDetails" variants additionally carry ``subsequentCallingPoints``; everything
else is shared, so detecting the shape by its keys keeps this to a single code path.
"""

from __future__ import annotations

import re
from typing import Any

from railinfo.domain.models import CallingPoint, DepartureBoard, Service

_TAG_RE = re.compile(r"<[^>]+>")


def from_ldbws(payload: dict[str, Any] | None) -> DepartureBoard:
    if not payload:
        return DepartureBoard(location_name=None, crs=None, generated_at=None)

    if "departures" in payload:
        services = [
            _map_service(item["service"])
            for item in (payload.get("departures") or [])
            if item.get("service")
        ]
    else:
        services = [_map_service(s) for s in (payload.get("trainServices") or [])]

    return DepartureBoard(
        location_name=payload.get("locationName"),
        crs=payload.get("crs"),
        generated_at=payload.get("generatedAt"),
        nrcc_messages=_nrcc_messages(payload),
        services=services,
    )


def _map_service(svc: dict[str, Any]) -> Service:
    destinations = svc.get("currentDestinations") or svc.get("destination") or []
    origins = svc.get("currentOrigins") or svc.get("origin") or []
    return Service(
        std=svc.get("std"),
        etd=svc.get("etd"),
        sta=svc.get("sta"),
        eta=svc.get("eta"),
        platform=svc.get("platform"),
        destination=_join_locations(destinations),
        origin=_join_locations(origins),
        via=_first_via(destinations),
        operator=svc.get("operator"),
        is_cancelled=bool(svc.get("isCancelled")),
        cancel_reason=svc.get("cancelReason"),
        delay_reason=svc.get("delayReason"),
        calling_points=_calling_points(svc.get("subsequentCallingPoints") or []),
        service_id=svc.get("serviceID"),
    )


def from_service_details(payload: dict[str, Any] | None) -> Service:
    """Map a ``ServiceDetails`` payload (GetServiceDetails) into a :class:`Service`.

    ServiceDetails has no destination/origin arrays — the destination is the last
    subsequent calling point and the origin is the first previous calling point.
    """
    if not payload:
        return Service(
            std=None, etd=None, sta=None, eta=None, platform=None,
            destination=None, origin=None, via=None, operator=None,
        )

    subsequent = _calling_points(payload.get("subsequentCallingPoints") or [])
    previous = _calling_points(payload.get("previousCallingPoints") or [])
    return Service(
        std=payload.get("std"),
        etd=payload.get("etd"),
        sta=payload.get("sta"),
        eta=payload.get("eta"),
        platform=payload.get("platform"),
        destination=subsequent[-1].location if subsequent else payload.get("locationName"),
        origin=previous[0].location if previous else None,
        via=None,
        operator=payload.get("operator"),
        is_cancelled=bool(payload.get("isCancelled")),
        cancel_reason=payload.get("cancelReason"),
        delay_reason=payload.get("delayReason"),
        calling_points=subsequent,
        service_id=payload.get("serviceID"),
    )


def _join_locations(locations: list[dict[str, Any]]) -> str | None:
    names = [loc.get("locationName") for loc in locations if loc.get("locationName")]
    return " & ".join(names) if names else None


def _first_via(locations: list[dict[str, Any]]) -> str | None:
    for loc in locations:
        if loc.get("via"):
            return loc["via"]
    return None


def _calling_points(groups: list[dict[str, Any]]) -> list[CallingPoint]:
    points: list[CallingPoint] = []
    for group in groups:
        for cp in group.get("callingPoint") or []:
            name = cp.get("locationName")
            if name:
                points.append(
                    CallingPoint(
                        location=name,
                        st=cp.get("st"),
                        et=cp.get("et"),
                        at=cp.get("at"),
                    )
                )
    return points


def _nrcc_messages(payload: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for msg in payload.get("nrccMessages") or []:
        text = msg.get("Value") or msg.get("value")
        if text:
            messages.append(_strip_html(text))
    return messages


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", text)).strip()
