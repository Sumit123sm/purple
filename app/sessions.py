from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.pos import conversion_window_start, get_store_transactions_for_date
from app.tables import EventRecord

SESSION_START_EVENTS = {"ENTRY", "REENTRY"}
ZONE_VISIT_EVENTS = {"ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL"}
BILLING_EVENTS = {"BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON"}
HEATMAP_ZONE_EVENTS = ZONE_VISIT_EVENTS | BILLING_EVENTS


@dataclass
class VisitorSession:
    visitor_id: str
    store_id: str
    start_event_type: str
    started_at: datetime
    events: list[EventRecord] = field(default_factory=list)

    @property
    def session_key(self) -> str:
        return f"{self.visitor_id}:{self.started_at.isoformat()}"

    def has_zone_visit(self) -> bool:
        return any(
            event.event_type in ZONE_VISIT_EVENTS and event.zone_id
            for event in self.events
        )

    def has_billing_queue(self) -> bool:
        return any(event.event_type == "BILLING_QUEUE_JOIN" for event in self.events)

    def billing_timestamps(self) -> list[datetime]:
        timestamps: list[datetime] = []
        for event in self.events:
            if event.event_type in BILLING_EVENTS:
                timestamps.append(as_utc(event.timestamp))
            elif event.zone_id == settings.billing_zone_id:
                timestamps.append(as_utc(event.timestamp))
        return timestamps


async def fetch_store_events(session: AsyncSession, store_id: str) -> list[EventRecord]:
    stmt = (
        select(EventRecord)
        .where(EventRecord.store_id == store_id)
        .order_by(EventRecord.timestamp.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def filter_customer_events_for_date(
    events: list[EventRecord],
    target_date: date,
) -> list[EventRecord]:
    return [
        event
        for event in events
        if not event.is_staff and as_utc(event.timestamp).date() == target_date
    ]


def resolve_target_date(
    customer_events: list[EventRecord],
    target_date: date | None,
) -> date:
    if target_date is not None:
        return target_date
    if customer_events:
        return as_utc(customer_events[-1].timestamp).date()
    return datetime.now(timezone.utc).date()


def build_sessions(events: list[EventRecord]) -> list[VisitorSession]:
    sessions: list[VisitorSession] = []
    events_by_visitor: dict[str, list[EventRecord]] = {}

    for event in sorted(events, key=lambda item: item.timestamp):
        events_by_visitor.setdefault(event.visitor_id, []).append(event)

    for visitor_id, visitor_events in events_by_visitor.items():
        current: list[EventRecord] = []
        for event in visitor_events:
            if event.event_type in SESSION_START_EVENTS:
                if current:
                    sessions.append(_make_session(current))
                current = [event]
                continue

            if not current:
                continue

            current.append(event)
            if event.event_type == "EXIT":
                sessions.append(_make_session(current))
                current = []

        if current:
            sessions.append(_make_session(current))

    return sessions


def session_has_purchase(
    session: VisitorSession,
    store_id: str,
    target_date: date,
) -> bool:
    billing_times = session.billing_timestamps()
    if not billing_times:
        return False

    for txn in get_store_transactions_for_date(store_id, target_date):
        window_start = conversion_window_start(txn.timestamp)
        window_end = txn.timestamp
        if any(window_start <= ts <= window_end for ts in billing_times):
            return True
    return False


def _make_session(events: list[EventRecord]) -> VisitorSession:
    start = events[0]
    return VisitorSession(
        visitor_id=start.visitor_id,
        store_id=start.store_id,
        start_event_type=start.event_type,
        started_at=as_utc(start.timestamp),
        events=list(events),
    )


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
