import json
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import StoreMetricsResponse
from app.pos import conversion_window_start, get_store_transactions_for_date
from app.tables import EventRecord

VISITOR_START_EVENTS = {"ENTRY", "REENTRY"}
BILLING_EVENTS = {"BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON"}


async def compute_store_metrics(
    session: AsyncSession,
    store_id: str,
    target_date: date | None = None,
) -> StoreMetricsResponse:
    events = await _fetch_store_events(session, store_id)
    customer_events = [event for event in events if not event.is_staff]

    if target_date is None:
        if customer_events:
            target_date = _as_utc(customer_events[-1].timestamp).date()
        else:
            target_date = datetime.now(timezone.utc).date()

    day_events = [
        event for event in customer_events if _as_utc(event.timestamp).date() == target_date
    ]

    unique_visitors = _unique_visitors(day_events)
    avg_dwell_per_zone = _avg_dwell_per_zone(day_events)
    queue_depth = _current_queue_depth(day_events)
    queue_joiners = _queue_join_visitors(day_events)
    queue_abandoners = _queue_abandon_visitors(day_events)
    converted_visitors = _converted_visitors(day_events, store_id, target_date)

    abandonment_rate = 0.0
    if queue_joiners:
        abandonment_rate = round(len(queue_abandoners) / len(queue_joiners), 4)

    conversion_rate = 0.0
    if unique_visitors:
        conversion_rate = round(converted_visitors / unique_visitors, 4)

    return StoreMetricsResponse(
        store_id=store_id,
        date=target_date.isoformat(),
        unique_visitors=unique_visitors,
        converted_visitors=converted_visitors,
        conversion_rate=conversion_rate,
        avg_dwell_per_zone=avg_dwell_per_zone,
        queue_depth=queue_depth,
        abandonment_rate=abandonment_rate,
        computed_at=datetime.now(timezone.utc),
    )


async def _fetch_store_events(session: AsyncSession, store_id: str) -> list[EventRecord]:
    stmt = (
        select(EventRecord)
        .where(EventRecord.store_id == store_id)
        .order_by(EventRecord.timestamp.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _unique_visitors(events: list[EventRecord]) -> int:
    visitors = {
        event.visitor_id
        for event in events
        if event.event_type in VISITOR_START_EVENTS
    }
    return len(visitors)


def _avg_dwell_per_zone(events: list[EventRecord]) -> dict[str, float]:
    dwell_totals: dict[str, list[int]] = defaultdict(list)
    for event in events:
        if event.event_type == "ZONE_DWELL" and event.zone_id:
            dwell_totals[event.zone_id].append(event.dwell_ms)

    return {
        zone: round(sum(values) / len(values), 2)
        for zone, values in sorted(dwell_totals.items())
    }


def _current_queue_depth(events: list[EventRecord]) -> int:
    latest_depth = 0
    latest_ts: datetime | None = None
    for event in events:
        if event.event_type != "BILLING_QUEUE_JOIN":
            continue
        metadata = json.loads(event.metadata_json)
        queue_depth = metadata.get("queue_depth")
        if queue_depth is None:
            continue
        event_ts = _as_utc(event.timestamp)
        if latest_ts is None or event_ts >= latest_ts:
            latest_ts = event_ts
            latest_depth = int(queue_depth)
    return latest_depth


def _queue_join_visitors(events: list[EventRecord]) -> set[str]:
    return {
        event.visitor_id
        for event in events
        if event.event_type == "BILLING_QUEUE_JOIN"
    }


def _queue_abandon_visitors(events: list[EventRecord]) -> set[str]:
    return {
        event.visitor_id
        for event in events
        if event.event_type == "BILLING_QUEUE_ABANDON"
    }


def _converted_visitors(
    events: list[EventRecord],
    store_id: str,
    target_date: date,
) -> int:
    billing_events = [
        event
        for event in events
        if _is_billing_zone_event(event)
    ]
    billing_by_visitor: dict[str, list[datetime]] = defaultdict(list)
    for event in billing_events:
        billing_by_visitor[event.visitor_id].append(_as_utc(event.timestamp))

    transactions = get_store_transactions_for_date(store_id, target_date)
    converted: set[str] = set()
    for txn in transactions:
        window_start = conversion_window_start(txn.timestamp)
        window_end = txn.timestamp
        for visitor_id, timestamps in billing_by_visitor.items():
            if any(window_start <= ts <= window_end for ts in timestamps):
                converted.add(visitor_id)
    return len(converted)


def _is_billing_zone_event(event: EventRecord) -> bool:
    if event.event_type in BILLING_EVENTS:
        return True
    return event.zone_id == settings.billing_zone_id


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
