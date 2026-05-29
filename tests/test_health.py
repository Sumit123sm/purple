# PROMPT: Write async FastAPI /health tests covering per-store last_event_at, feed_status OK/STALE,
# STALE_FEED warnings when lag > 10 minutes, degraded status, fresh feed after ingest, and 503 on DB failure.
# CHANGES MADE: Replaced stub health tests with feed-state assertions; added stale vs fresh scenarios.

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError


@pytest.mark.asyncio
async def test_health_returns_ok_with_no_stores(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert body["warnings"] == []
    assert body["stores"] == {}


@pytest.mark.asyncio
async def test_health_includes_trace_id_header(client):
    response = await client.get("/health", headers={"X-Trace-Id": "test-trace-123"})
    assert response.headers.get("X-Trace-Id") == "test-trace-123"


@pytest.mark.asyncio
async def test_health_generates_trace_id_when_missing(client):
    response = await client.get("/health")
    assert response.headers.get("X-Trace-Id")


@pytest.mark.asyncio
async def test_health_reports_store_feed_after_ingest(client, sample_events_from_file):
    await client.post("/events/ingest", json={"events": sample_events_from_file})
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert "STORE_BLR_002" in body["stores"]
    store = body["stores"]["STORE_BLR_002"]
    assert store["last_event_at"] == "2026-03-03T14:45:00Z"
    assert store["feed_status"] == "STALE"
    assert store["lag_minutes"] > 10
    assert any("STALE_FEED" in warning for warning in body["warnings"])
    assert body["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_fresh_feed_is_ok(client):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ts = now.isoformat().replace("+00:00", "Z")
    event = {
        "event_id": str(uuid4()),
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_fresh",
        "event_type": "ENTRY",
        "timestamp": ts,
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {},
    }
    await client.post("/events/ingest", json={"events": [event]})
    response = await client.get("/health")

    body = response.json()
    store = body["stores"]["STORE_BLR_002"]
    assert store["feed_status"] == "OK"
    assert store["lag_minutes"] <= 10
    assert body["status"] == "ok"
    assert body["warnings"] == []


@pytest.mark.asyncio
async def test_health_database_unavailable_returns_503(client):
    with patch("app.routes.health.compute_health", side_effect=OperationalError("", {}, Exception())):
        response = await client.get("/health")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "service_unavailable"
    assert "trace_id" in detail
