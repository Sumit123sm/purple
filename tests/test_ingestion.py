# PROMPT: Write pytest tests for POST /events/ingest FastAPI endpoint.
# Cover: batch accept, idempotency (same event_id twice), partial success on malformed events,
# structured error response, max 500 batch limit, duplicate counting, store feed state update.
# CHANGES MADE: Added fixture-based sample_events.jsonl ingest test and OperationalError 503 mock.

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from app.ingestion import count_events


class TestIngestEndpoint:
    @pytest.mark.asyncio
    async def test_ingest_valid_batch(self, client, sample_events_from_file):
        response = await client.post("/events/ingest", json={"events": sample_events_from_file})
        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] == 5
        assert body["duplicates"] == 0
        assert body["rejected"] == 0
        assert body["errors"] == []

    @pytest.mark.asyncio
    async def test_ingest_idempotent(self, client, sample_events_from_file):
        first = await client.post("/events/ingest", json={"events": sample_events_from_file})
        second = await client.post("/events/ingest", json={"events": sample_events_from_file})

        assert first.json()["accepted"] == 5
        second_body = second.json()
        assert second_body["accepted"] == 0
        assert second_body["duplicates"] == 5
        assert second_body["rejected"] == 0

    @pytest.mark.asyncio
    async def test_ingest_partial_success(self, client):
        good = {
            "event_id": str(uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": "VIS_good",
            "event_type": "ENTRY",
            "timestamp": "2026-03-03T14:22:10Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.9,
            "metadata": {},
        }
        bad = {"event_id": "not-a-uuid", "event_type": "ENTRY"}
        response = await client.post("/events/ingest", json={"events": [good, bad]})

        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] == 1
        assert body["rejected"] == 1
        assert len(body["errors"]) == 1
        assert "event_id" in body["errors"][0]
        assert "message" in body["errors"][0]

    @pytest.mark.asyncio
    async def test_ingest_rejects_over_500_events(self, client):
        events = [
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": f"VIS_{i}",
                "event_type": "ENTRY",
                "timestamp": "2026-03-03T14:22:10Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            }
            for i in range(501)
        ]
        response = await client.post("/events/ingest", json={"events": events})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_ingest_empty_batch(self, client):
        response = await client.post("/events/ingest", json={"events": []})
        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] == 0
        assert body["duplicates"] == 0
        assert body["rejected"] == 0

    @pytest.mark.asyncio
    async def test_ingest_mixed_new_and_duplicate(self, client):
        event_id = str(uuid4())
        event = {
            "event_id": event_id,
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": "VIS_mix",
            "event_type": "ENTRY",
            "timestamp": "2026-03-03T14:22:10Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.9,
            "metadata": {},
        }
        await client.post("/events/ingest", json={"events": [event]})

        duplicate = dict(event)
        new_event = dict(event, event_id=str(uuid4()), visitor_id="VIS_new")
        response = await client.post("/events/ingest", json={"events": [duplicate, new_event]})

        body = response.json()
        assert body["accepted"] == 1
        assert body["duplicates"] == 1

    @pytest.mark.asyncio
    async def test_ingest_returns_trace_id_header(self, client, sample_events_from_file):
        response = await client.post(
            "/events/ingest",
            json={"events": sample_events_from_file[:1]},
            headers={"X-Trace-Id": "ingest-trace-99"},
        )
        assert response.headers.get("X-Trace-Id") == "ingest-trace-99"

    @pytest.mark.asyncio
    async def test_ingest_database_unavailable_returns_503(self, client, sample_events_from_file):
        with patch("app.routes.ingest.ingest_events", new_callable=AsyncMock) as mock_ingest:
            mock_ingest.side_effect = OperationalError("connection failed", {}, Exception())
            response = await client.post(
                "/events/ingest",
                json={"events": sample_events_from_file[:1]},
            )

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["error"] == "service_unavailable"
        assert "trace_id" in detail


class TestIngestPersistence:
    @pytest.mark.asyncio
    async def test_events_persisted_to_db(self, client, db_session, sample_events_from_file):
        await client.post("/events/ingest", json={"events": sample_events_from_file})
        total = await count_events(db_session, store_id="STORE_BLR_002")
        assert total == 5
