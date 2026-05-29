from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import HealthResponse
from app.sessions import as_utc
from app.tables import StoreFeedState


async def compute_health(session: AsyncSession) -> HealthResponse:
    now = datetime.now(timezone.utc)
    stores: dict[str, dict] = {}
    warnings: list[str] = []

    try:
        result = await session.execute(select(StoreFeedState))
        feed_states = list(result.scalars().all())
    except OperationalError:
        raise

    for feed in feed_states:
        last_event_at = as_utc(feed.last_event_at)
        lag_minutes = round((now - last_event_at).total_seconds() / 60, 2)
        is_stale = lag_minutes > settings.health_stale_feed_minutes
        feed_status = "STALE" if is_stale else "OK"

        stores[feed.store_id] = {
            "last_event_at": last_event_at.isoformat().replace("+00:00", "Z"),
            "lag_minutes": lag_minutes,
            "feed_status": feed_status,
        }

        if is_stale:
            warnings.append(
                f"STALE_FEED store={feed.store_id} lag_minutes={lag_minutes}"
            )

    status = "degraded" if warnings else "ok"
    return HealthResponse(
        status=status,
        version=settings.app_version,
        stores=stores,
        warnings=warnings,
    )
