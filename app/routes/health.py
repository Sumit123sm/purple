import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_trace_id
from app.health_service import compute_health
from app.models import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HealthResponse:
    try:
        return await compute_health(db)
    except OperationalError as exc:
        logger.error(
            "database_unavailable trace_id=%s endpoint=/health error=%s",
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
