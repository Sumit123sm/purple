from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FunnelResponse, FunnelStage
from app.sessions import (
    build_sessions,
    fetch_store_events,
    filter_customer_events_for_date,
    resolve_target_date,
    session_has_purchase,
)

FUNNEL_STAGES = (
    ("entry", lambda session: True),
    ("zone_visit", lambda session: session.has_zone_visit()),
    ("billing_queue", lambda session: session.has_billing_queue()),
    ("purchase", None),
)


async def compute_store_funnel(
    session: AsyncSession,
    store_id: str,
    target_date: date | None = None,
) -> FunnelResponse:
    events = await fetch_store_events(session, store_id)
    customer_events = [event for event in events if not event.is_staff]
    resolved_date = resolve_target_date(customer_events, target_date)
    day_events = filter_customer_events_for_date(customer_events, resolved_date)
    sessions = build_sessions(day_events)

    stage_counts: dict[str, int] = {}
    for stage_name, predicate in FUNNEL_STAGES:
        if stage_name == "purchase":
            stage_counts[stage_name] = sum(
                1 for item in sessions if session_has_purchase(item, store_id, resolved_date)
            )
        else:
            stage_counts[stage_name] = sum(1 for item in sessions if predicate(item))

    stages: list[FunnelStage] = []
    previous_count: int | None = None
    for stage_name, _ in FUNNEL_STAGES:
        count = stage_counts[stage_name]
        drop_off = 0.0
        if previous_count is not None and previous_count > 0:
            drop_off = round(((previous_count - count) / previous_count) * 100, 2)
        stages.append(FunnelStage(stage=stage_name, count=count, drop_off_pct=drop_off))
        previous_count = count

    return FunnelResponse(
        store_id=store_id,
        date=resolved_date.isoformat(),
        total_sessions=len(sessions),
        stages=stages,
        computed_at=datetime.now(timezone.utc),
    )
