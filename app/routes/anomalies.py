import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.anomalies import compute_store_anomalies
from app.dependencies import get_db, get_trace_id
from app.models import AnomaliesResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stores"])


@router.get("/stores/{store_id}/anomalies", response_model=AnomaliesResponse)
async def get_store_anomalies(
    store_id: str,
    request: Request,
    target_date: date | None = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
) -> AnomaliesResponse:
    request.state.store_id = store_id

    try:
        anomalies = await compute_store_anomalies(db, store_id, target_date)
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

    return anomalies
