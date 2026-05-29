import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_trace_id
from app.funnel import compute_store_funnel
from app.models import FunnelResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stores"])


@router.get("/stores/{store_id}/funnel", response_model=FunnelResponse)
async def get_store_funnel(
    store_id: str,
    request: Request,
    target_date: date | None = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
) -> FunnelResponse:
    request.state.store_id = store_id

    try:
        funnel = await compute_store_funnel(db, store_id, target_date)
    except OperationalError as exc:
        logger.error(
            "database_unavailable trace_id=%s store_id=%s error=%s",
            get_trace_id(request),
            store_id,
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

    return funnel
