from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import EventSourceResponse

from app.dependencies import get_db
from app.metrics import compute_store_metrics

router = APIRouter()


@router.get("/dashboard/stream", response_class=EventSourceResponse)
async def dashboard_stream(
    store_id: str = Query(...),
    target_date: date | None = Query(default=None, alias="date"),
    db=Depends(get_db),
) -> EventSourceResponse:
    async def event_publisher() -> AsyncGenerator[str, None]:
        # Simple poller: fetch metrics every second and push via SSE.
        # This keeps the demo working without requiring a separate pub/sub hub.
        try:
            while True:
                try:
                    metrics = await compute_store_metrics(db, store_id, target_date)
                except Exception as exc:
                    # Yield an error event and stop the stream.
                    err = {"error": "metrics_error", "message": str(exc)}
                    yield f"data: {json.dumps(err)}\n\n"
                    return

                # Server-Sent Events expect text/event-stream; send JSON payload.
                payload = json.dumps(metrics.model_dump(), default=str)
                yield f"data: {payload}\n\n"
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return

    return EventSourceResponse(event_publisher())
