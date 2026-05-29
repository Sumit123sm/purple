# PROMPT: Write pytest tests for GET /stores/{id}/heatmap covering zone visit frequency,
# avg dwell normalized 0-100, raw counts, data_confidence LOW when sessions < 20,
# empty store, staff exclusion, and 503 on DB failure.
# CHANGES MADE: Added multi-zone normalization test and HIGH confidence test with 20 sessions.

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

FIXTURES = Path(__file__).parent / "fixtures"


class TestStoreHeatmapEndpoint:
    @pytest.mark.asyncio
    async def test_heatmap_with_sample_events(self, client, sample_events_from_file):
        await client.post("/events/ingest", json={"events": sample_events_from_file})
        response = await client.get("/stores/STORE_BLR_002/heatmap?date=2026-03-03")

        assert response.status_code == 200
        body = response.json()
        assert body["store_id"] == "STORE_BLR_002"
        assert body["session_count"] == 1
        assert body["data_confidence"] == "LOW"

        zones = {zone["zone_id"]: zone for zone in body["zones"]}
        assert "SKINCARE" in zones
        assert zones["SKINCARE"]["visit_count"] == 1
        assert zones["SKINCARE"]["visit_frequency"] == 100
        assert zones["SKINCARE"]["avg_dwell_ms"] == 30000.0
        assert zones["SKINCARE"]["avg_dwell"] == 100
        assert "BILLING" in zones
        assert zones["BILLING"]["visit_count"] == 1

    @pytest.mark.asyncio
    async def test_heatmap_empty_store(self, client):
        response = await client.get("/stores/STORE_EMPTY_001/heatmap?date=2026-03-03")

        assert response.status_code == 200
        body = response.json()
        assert body["session_count"] == 0
        assert body["data_confidence"] == "LOW"
        assert body["zones"] == []

    @pytest.mark.asyncio
    async def test_heatmap_normalizes_across_zones(self, client):
        events = [
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_a",
                "event_type": "ENTRY",
                "timestamp": "2026-03-09T10:00:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_FLOOR_01",
                "visitor_id": "VIS_a",
                "event_type": "ZONE_ENTER",
                "timestamp": "2026-03-09T10:05:00Z",
                "zone_id": "SKINCARE",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_FLOOR_01",
                "visitor_id": "VIS_a",
                "event_type": "ZONE_DWELL",
                "timestamp": "2026-03-09T10:06:00Z",
                "zone_id": "SKINCARE",
                "dwell_ms": 20000,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_b",
                "event_type": "ENTRY",
                "timestamp": "2026-03-09T10:01:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_FLOOR_01",
                "visitor_id": "VIS_b",
                "event_type": "ZONE_ENTER",
                "timestamp": "2026-03-09T10:07:00Z",
                "zone_id": "FRAGRANCE",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_FLOOR_01",
                "visitor_id": "VIS_b",
                "event_type": "ZONE_DWELL",
                "timestamp": "2026-03-09T10:08:00Z",
                "zone_id": "FRAGRANCE",
                "dwell_ms": 10000,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_FLOOR_01",
                "visitor_id": "VIS_c",
                "event_type": "ENTRY",
                "timestamp": "2026-03-09T10:02:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_FLOOR_01",
                "visitor_id": "VIS_c",
                "event_type": "ZONE_ENTER",
                "timestamp": "2026-03-09T10:09:00Z",
                "zone_id": "FRAGRANCE",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
        ]
        await client.post("/events/ingest", json={"events": events})
        response = await client.get("/stores/STORE_BLR_002/heatmap?date=2026-03-09")

        zones = {zone["zone_id"]: zone for zone in response.json()["zones"]}
        assert zones["FRAGRANCE"]["visit_count"] == 2
        assert zones["SKINCARE"]["visit_count"] == 1
        assert zones["FRAGRANCE"]["visit_frequency"] == 100
        assert zones["SKINCARE"]["visit_frequency"] == 50
        assert zones["FRAGRANCE"]["avg_dwell"] == 50
        assert zones["SKINCARE"]["avg_dwell"] == 100

    @pytest.mark.asyncio
    async def test_heatmap_high_confidence_with_20_sessions(self, client):
        events = []
        for i in range(20):
            visitor = f"VIS_{i:02d}"
            events.extend(
                [
                    {
                        "event_id": str(uuid4()),
                        "store_id": "STORE_BLR_002",
                        "camera_id": "CAM_ENTRY_01",
                        "visitor_id": visitor,
                        "event_type": "ENTRY",
                        "timestamp": f"2026-03-10T{10 + (i // 60):02d}:{i % 60:02d}:00Z",
                        "zone_id": None,
                        "dwell_ms": 0,
                        "is_staff": False,
                        "confidence": 0.9,
                        "metadata": {},
                    },
                    {
                        "event_id": str(uuid4()),
                        "store_id": "STORE_BLR_002",
                        "camera_id": "CAM_FLOOR_01",
                        "visitor_id": visitor,
                        "event_type": "ZONE_ENTER",
                        "timestamp": f"2026-03-10T{10 + (i // 60):02d}:{(i % 60) + 1:02d}:00Z",
                        "zone_id": "SKINCARE",
                        "dwell_ms": 0,
                        "is_staff": False,
                        "confidence": 0.9,
                        "metadata": {},
                    },
                ]
            )

        await client.post("/events/ingest", json={"events": events})
        response = await client.get("/stores/STORE_BLR_002/heatmap?date=2026-03-10")

        assert response.json()["session_count"] == 20
        assert response.json()["data_confidence"] == "HIGH"

    @pytest.mark.asyncio
    async def test_heatmap_excludes_staff(self, client):
        events = [
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_staff",
                "event_type": "ENTRY",
                "timestamp": "2026-03-11T09:00:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": True,
                "confidence": 0.95,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_FLOOR_01",
                "visitor_id": "VIS_staff",
                "event_type": "ZONE_ENTER",
                "timestamp": "2026-03-11T09:05:00Z",
                "zone_id": "SKINCARE",
                "dwell_ms": 0,
                "is_staff": True,
                "confidence": 0.95,
                "metadata": {},
            },
        ]
        await client.post("/events/ingest", json={"events": events})
        response = await client.get("/stores/STORE_BLR_002/heatmap?date=2026-03-11")

        body = response.json()
        assert body["session_count"] == 0
        assert body["zones"] == []

    @pytest.mark.asyncio
    async def test_heatmap_database_unavailable_returns_503(self, client):
        with patch("app.routes.heatmap.compute_store_heatmap", side_effect=OperationalError("", {}, Exception())):
            response = await client.get("/stores/STORE_BLR_002/heatmap")

        assert response.status_code == 503
