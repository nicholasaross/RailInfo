"""Application service layer — the seam a Phase 3 HTTP API would wrap.

Each function fetches from one LDBWS product and returns a normalised
:class:`~railinfo.domain.models.DepartureBoard`. Callers (CLI, renderers, a future
FastAPI app) depend only on this and the domain model, never on the HTTP client or the
raw schema.
"""

from __future__ import annotations

import dataclasses

from railinfo.config import Settings
from railinfo.domain.mapper import from_ldbws, from_service_details
from railinfo.domain.models import DepartureBoard, Service
from railinfo.ldbws.client import LdbwsClient, LdbwsError


class BoardService:
    def __init__(self, settings: Settings, client: LdbwsClient | None = None) -> None:
        self._settings = settings
        self._client = client or LdbwsClient()

    def get_departure_board(
        self, crs: str | None = None, with_details: bool = False
    ) -> DepartureBoard:
        """Primary board: Live Departure Board (_LDB).

        When ``with_details`` is set and the Service Details endpoint (_SD) is configured,
        each service is enriched with its calling points via GetServiceDetails.
        """
        board = self._fetch("ldb", crs)
        if with_details and "sd" in self._settings.endpoints:
            board = dataclasses.replace(
                board, services=[self._with_calling_points(s) for s in board.services]
            )
        return board

    def get_service_details(self, service_id: str) -> Service:
        """Full detail (incl. calling points) for one service (_SD)."""
        endpoint = self._settings.endpoint("sd")
        return from_service_details(self._client.get_service_details(endpoint, service_id))

    def _with_calling_points(self, service: Service) -> Service:
        if not service.service_id or service.calling_points:
            return service
        try:
            details = self.get_service_details(service.service_id)
        except LdbwsError:
            return service  # leave the row intact if detail lookup fails
        return dataclasses.replace(
            service,
            calling_points=details.calling_points,
            destination=service.destination or details.destination,
        )

    def get_arr_dep_board(self, crs: str | None = None) -> DepartureBoard:
        """Combined arrivals + departures with calling points (_LADB)."""
        return self._fetch("ladb", crs)

    def get_next_departures(
        self, crs: str | None = None, filter_list: list[str] | None = None
    ) -> DepartureBoard:
        """Next train to each filtered destination (_LNDB)."""
        return self._fetch(
            "lndb", crs, filter_list=filter_list or self._settings.filter_crs_list
        )

    def _fetch(
        self, endpoint_name: str, crs: str | None, filter_list: list[str] | None = None
    ) -> DepartureBoard:
        endpoint = self._settings.endpoint(endpoint_name)
        payload = self._client.get_board(
            endpoint,
            crs or self._settings.station_crs,
            filter_list=filter_list,
            time_offset=self._settings.time_offset,
            time_window=self._settings.time_window,
        )
        return from_ldbws(payload)
