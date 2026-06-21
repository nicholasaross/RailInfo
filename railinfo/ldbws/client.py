"""Thin HTTP client for the Rail Data Marketplace LDBWS REST API.

The client is deliberately dumb: it substitutes the placeholders in an
:class:`~railinfo.config.Endpoint` URL template (``{crs}`` / ``{filterList}`` for boards,
``{serviceid}`` for service details), sets the per-endpoint ``x-apikey`` header, and
returns parsed JSON. It knows nothing about the response shape — that is the mapper's job.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from railinfo.config import Endpoint


class LdbwsError(RuntimeError):
    """A friendly, user-facing error for an LDBWS request failure."""


class LdbwsClient:
    def __init__(self, *, timeout: float = 15.0) -> None:
        self._timeout = timeout

    def get_board(
        self,
        endpoint: Endpoint,
        crs: str,
        *,
        filter_list: list[str] | None = None,
        time_offset: int = 0,
        time_window: int = 120,
    ) -> dict[str, Any]:
        substitutions: dict[str, str] = {"crs": crs.strip().upper()}
        if "{filterList}" in endpoint.url_template:
            if not filter_list:
                raise LdbwsError(
                    f"The '{endpoint.name}' endpoint requires a filter list of "
                    "destination CRS codes, but none was provided."
                )
            substitutions["filterList"] = ",".join(
                c.strip().upper() for c in filter_list
            )
        url = self._build_url(endpoint, substitutions)
        return self._request(
            endpoint, url, params={"timeOffset": time_offset, "timeWindow": time_window}
        )

    def get_service_details(self, endpoint: Endpoint, service_id: str) -> dict[str, Any]:
        url = self._build_url(endpoint, {"serviceid": quote(service_id, safe="")})
        return self._request(endpoint, url)

    def _build_url(self, endpoint: Endpoint, substitutions: dict[str, str]) -> str:
        try:
            return endpoint.url_template.format(**substitutions)
        except KeyError as exc:
            raise LdbwsError(
                f"URL template for '{endpoint.name}' has an unexpected placeholder: {exc}."
            ) from exc

    def _request(
        self, endpoint: Endpoint, url: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {"x-apikey": endpoint.api_key, "Accept": "application/json"}
        try:
            response = httpx.get(
                url, headers=headers, params=params, timeout=self._timeout
            )
        except httpx.RequestError as exc:
            raise LdbwsError(f"Could not reach LDBWS ({endpoint.name}): {exc}") from exc

        self._raise_for_status(endpoint, response)

        try:
            return response.json()
        except ValueError as exc:
            raise LdbwsError(
                f"LDBWS ({endpoint.name}) returned a non-JSON response "
                f"(HTTP {response.status_code})."
            ) from exc

    @staticmethod
    def _raise_for_status(endpoint: Endpoint, response: httpx.Response) -> None:
        if response.is_success:
            return
        env_suffix = endpoint.name.upper()
        if response.status_code in (401, 403):
            raise LdbwsError(
                f"Authentication failed for '{endpoint.name}' (HTTP "
                f"{response.status_code}). Check BWS_API_KEY_{env_suffix} in .env."
            )
        if response.status_code == 400:
            raise LdbwsError(
                f"LDBWS '{endpoint.name}' rejected the request (HTTP 400) — check the "
                "CRS code is a valid 3-letter station code."
            )
        if response.status_code == 404:
            raise LdbwsError(
                f"LDBWS '{endpoint.name}' returned 404 — check the CRS code and the "
                f"LDBWS_BASE_URL_{env_suffix} template in .env."
            )
        raise LdbwsError(
            f"LDBWS '{endpoint.name}' request failed with HTTP {response.status_code}."
        )
