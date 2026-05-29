import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_trace_id
from app.ingestion import IngestPayload, ingest_events
from app.models import IngestResult

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])


@router.post("/events/ingest", response_model=IngestResult)
async def ingest_event_batch(
    request: Request,
    payload: IngestPayload,
    db: AsyncSession = Depends(get_db),
) -> IngestResult:
    store_ids = {str(e.get("store_id", "")) for e in payload.events if e.get("store_id")}
    request.state.store_id = next(iter(store_ids), "-")
    request.state.event_count = len(payload.events)

    try:
        result = await ingest_events(db, payload.events)
    except OperationalError as exc:
        logger.error(
            "database_unavailable trace_id=%s error=%s",
            get_trace_id(request),
            str(exc),
        )
        raise HTTPException(
            status_code=503,
            detail={
                "error": "service_unavailable",
                "message": "Database is temporarily unavailable.",
                "trace_id": get_trace_id(request),
            },
        ) from exc

    logger.info(
        "ingest_complete trace_id=%s accepted=%s duplicates=%s rejected=%s",
        get_trace_id(request),
        result.accepted,
        result.duplicates,
        result.rejected,
    )
    return result
