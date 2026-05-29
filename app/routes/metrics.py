import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_trace_id
from app.metrics import compute_store_metrics
from app.models import StoreMetricsResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stores"])


@router.get("/stores/{store_id}/metrics", response_model=StoreMetricsResponse)
async def get_store_metrics(
    store_id: str,
    request: Request,
    target_date: date | None = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
) -> StoreMetricsResponse:
    request.state.store_id = store_id

    try:
        metrics = await compute_store_metrics(db, store_id, target_date)
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

    return metrics
