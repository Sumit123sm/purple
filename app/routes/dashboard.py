from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import EventSourceResponse

from app.metrics import compute_store_metrics
from app.database import SessionLocal

router = APIRouter()


@router.get("/dashboard/stream", response_class=EventSourceResponse)
async def dashboard_stream(
    store_id: str = Query(...),
    target_date: date | None = Query(default=None, alias="date"),
) -> EventSourceResponse:
    async def event_publisher() -> AsyncGenerator[str, None]:
        # Simple poller: fetch metrics every second and push via SSE.
        # Create a fresh DB session per iteration to avoid session lifecycle issues.
        try:
            while True:
                async with SessionLocal() as session:
                    try:
                        metrics = await compute_store_metrics(session, store_id, target_date)
                    except Exception as exc:
                        err = {"error": "metrics_error", "message": str(exc)}
                        yield f"data: {json.dumps(err)}\n\n"
                        return

                    payload = json.dumps(metrics.model_dump(), default=str)
                    yield f"data: {payload}\n\n"

                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # pragma: no cover - defensive logging for runtime
            import traceback, sys

            traceback.print_exc(file=sys.stderr)
            err = {"error": "stream_failure", "message": str(exc)}
            yield f"data: {json.dumps(err)}\n\n"
            return

    return EventSourceResponse(event_publisher())
