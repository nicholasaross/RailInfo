"""Render a :class:`~railinfo.domain.models.DepartureBoard` to the terminal.

A National-Rail-style board: a header rule, one line per service
(``Time  Destination  Plat  Expected``), an optional "calling at…" line when the
endpoint supplies calling points, and any NRCC service messages.
"""

from __future__ import annotations

from datetime import datetime

from rich.console import Console

from railinfo.domain.models import DepartureBoard, Service

_DEST_WIDTH = 36


def render(
    board: DepartureBoard,
    *,
    console: Console | None = None,
    show_calling_points: bool = True,
) -> None:
    console = console or Console()

    title = board.location_name or board.crs or "Departure board"
    if board.location_name and board.crs:
        title = f"{board.location_name} ({board.crs})"
    generated = _short_time(board.generated_at)
    heading = f"[bold]{title}[/bold]"
    if generated:
        heading += f"  -  {generated}"
    console.rule(heading)

    if not board.services:
        console.print("[yellow]No services are currently listed for this board.[/yellow]")
    else:
        for service in board.services:
            _render_service(console, service, show_calling_points)

    for message in board.nrcc_messages:
        console.print(f"[dim](i) {message}[/dim]")


def _render_service(
    console: Console, service: Service, show_calling_points: bool
) -> None:
    destination = service.destination or "—"
    if service.via:
        destination = f"{destination}  {service.via}"
    destination = _truncate(destination, _DEST_WIDTH)
    platform = f"Plat {service.platform}" if service.platform else "Plat -"

    if service.is_cancelled:
        colour = "red"
    elif service.expected == "On time":
        colour = "green"
    else:
        colour = "yellow"

    console.print(
        f"[bold]{service.time:<6}[/bold] {destination:<{_DEST_WIDTH}} "
        f"{platform:<8} [{colour}]{service.expected}[/{colour}]"
    )

    if show_calling_points and service.calling_points:
        stops = ", ".join(cp.location for cp in service.calling_points)
        console.print(f"       [dim]calling at:[/dim] {stops}")

    reason = service.cancel_reason or service.delay_reason
    if reason:
        console.print(f"       [red]{reason}[/red]")


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."


def _short_time(iso_timestamp: str | None) -> str | None:
    if not iso_timestamp:
        return None
    try:
        return datetime.fromisoformat(iso_timestamp).strftime("%H:%M:%S")
    except ValueError:
        return iso_timestamp
