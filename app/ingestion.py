import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IngestResult, StoreEvent
from app.tables import EventRecord, StoreFeedState


class IngestPayload(BaseModel):
    """Loose ingest body — events validated individually for partial success."""

    events: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


async def ingest_events(session: AsyncSession, raw_events: list[dict[str, Any]]) -> IngestResult:
    accepted = 0
    duplicates = 0
    rejected = 0
    errors: list[dict[str, str]] = []

    for index, raw in enumerate(raw_events):
        event_id_hint = str(raw.get("event_id", f"index:{index}"))

        try:
            event = StoreEvent.model_validate(raw)
        except ValidationError as exc:
            rejected += 1
            errors.append(
                {
                    "event_id": event_id_hint,
                    "index": str(index),
                    "message": "; ".join(err["msg"] for err in exc.errors()),
                }
            )
            continue

        insert_stmt = (
            sqlite_insert(EventRecord)
            .values(
                event_id=str(event.event_id),
                store_id=event.store_id,
                camera_id=event.camera_id,
                visitor_id=event.visitor_id,
                event_type=event.event_type.value,
                timestamp=event.timestamp,
                zone_id=event.zone_id,
                dwell_ms=event.dwell_ms,
                is_staff=event.is_staff,
                confidence=event.confidence,
                metadata_json=json.dumps(event.metadata.model_dump()),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        result = await session.execute(insert_stmt)

        if result.rowcount == 0:
            duplicates += 1
        else:
            accepted += 1
            await _update_store_feed_state(session, event.store_id, event.timestamp)

    return IngestResult(
        accepted=accepted,
        duplicates=duplicates,
        rejected=rejected,
        errors=errors,
    )


async def _update_store_feed_state(
    session: AsyncSession,
    store_id: str,
    event_timestamp: datetime,
) -> None:
    event_ts = _as_utc(event_timestamp)
    existing = await session.get(StoreFeedState, store_id)
    if existing is None:
        session.add(StoreFeedState(store_id=store_id, last_event_at=event_ts))
    elif event_ts > _as_utc(existing.last_event_at):
        existing.last_event_at = event_ts


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def count_events(session: AsyncSession, store_id: str | None = None) -> int:
    stmt = select(EventRecord)
    if store_id:
        stmt = stmt.where(EventRecord.store_id == store_id)
    result = await session.execute(stmt)
    return len(result.scalars().all())
