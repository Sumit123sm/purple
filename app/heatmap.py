from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import HeatmapResponse, HeatmapZone
from app.sessions import (
    HEATMAP_ZONE_EVENTS,
    build_sessions,
    fetch_store_events,
    filter_customer_events_for_date,
    resolve_target_date,
)


async def compute_store_heatmap(
    session: AsyncSession,
    store_id: str,
    target_date: date | None = None,
) -> HeatmapResponse:
    events = await fetch_store_events(session, store_id)
    customer_events = [event for event in events if not event.is_staff]
    resolved_date = resolve_target_date(customer_events, target_date)
    day_events = filter_customer_events_for_date(customer_events, resolved_date)
    sessions = build_sessions(day_events)

    visit_counts = _session_visit_counts(sessions)
    avg_dwell_ms = _avg_dwell_by_zone(day_events)

    all_zones = sorted(set(visit_counts) | set(avg_dwell_ms))
    visit_normalized = _normalize_to_100({zone: float(visit_counts.get(zone, 0)) for zone in all_zones})
    dwell_normalized = _normalize_to_100({zone: avg_dwell_ms.get(zone, 0.0) for zone in all_zones})

    zones = [
        HeatmapZone(
            zone_id=zone,
            visit_frequency=visit_normalized.get(zone, 0),
            avg_dwell=dwell_normalized.get(zone, 0),
            visit_count=visit_counts.get(zone, 0),
            avg_dwell_ms=round(avg_dwell_ms.get(zone, 0.0), 2),
        )
        for zone in all_zones
    ]

    session_count = len(sessions)
    data_confidence = (
        "HIGH"
        if session_count >= settings.heatmap_confidence_session_threshold
        else "LOW"
    )

    return HeatmapResponse(
        store_id=store_id,
        date=resolved_date.isoformat(),
        session_count=session_count,
        data_confidence=data_confidence,
        zones=zones,
        computed_at=datetime.now(timezone.utc),
    )


def _session_visit_counts(sessions) -> dict[str, int]:
    counts: dict[str, int] = {}
    for session in sessions:
        visited = {
            event.zone_id
            for event in session.events
            if event.zone_id and event.event_type in HEATMAP_ZONE_EVENTS
        }
        for zone_id in visited:
            counts[zone_id] = counts.get(zone_id, 0) + 1
    return counts


def _avg_dwell_by_zone(events) -> dict[str, float]:
    dwell_values: dict[str, list[int]] = {}
    for event in events:
        if event.event_type == "ZONE_DWELL" and event.zone_id:
            dwell_values.setdefault(event.zone_id, []).append(event.dwell_ms)

    return {
        zone: sum(values) / len(values)
        for zone, values in dwell_values.items()
    }


def _normalize_to_100(values: dict[str, float]) -> dict[str, int]:
    if not values:
        return {}
    peak = max(values.values())
    if peak <= 0:
        return {key: 0 for key in values}
    return {key: round((value / peak) * 100) for key, value in values.items()}
