# PROMPT: Write pytest tests for GET /stores/{id}/metrics covering unique visitors, conversion rate
# with POS correlation (5-min billing window), avg dwell per zone, queue depth, abandonment rate,
# staff exclusion, zero-traffic store, zero-purchase store. Use FastAPI async client.
# CHANGES MADE: Added POS fixture path monkeypatch, date query param for historical clip data,
# and explicit staff-only visitor exclusion test.

from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

FIXTURES = Path(__file__).parent / "fixtures"
POS_FIXTURE = FIXTURES / "pos_transactions.csv"


@pytest.fixture(autouse=True)
def use_test_pos_file(monkeypatch):
    monkeypatch.setenv("POS_TRANSACTIONS_PATH", str(POS_FIXTURE))
    from app.config import Settings

    monkeypatch.setattr(
        "app.config.settings",
        Settings(pos_transactions_path=str(POS_FIXTURE)),
    )
    monkeypatch.setattr(
        "app.pos.settings",
        Settings(pos_transactions_path=str(POS_FIXTURE)),
    )


class TestStoreMetricsEndpoint:
    @pytest.mark.asyncio
    async def test_metrics_with_sample_events(self, client, sample_events_from_file):
        await client.post("/events/ingest", json={"events": sample_events_from_file})
        response = await client.get("/stores/STORE_BLR_002/metrics?date=2026-03-03")

        assert response.status_code == 200
        body = response.json()
        assert body["store_id"] == "STORE_BLR_002"
        assert body["date"] == "2026-03-03"
        assert body["unique_visitors"] == 1
        assert body["converted_visitors"] == 1
        assert body["conversion_rate"] == 1.0
        assert body["avg_dwell_per_zone"]["SKINCARE"] == 30000.0
        assert body["queue_depth"] == 3
        assert body["abandonment_rate"] == 0.0
        assert "computed_at" in body

    @pytest.mark.asyncio
    async def test_metrics_empty_store_returns_zeros(self, client):
        response = await client.get("/stores/STORE_EMPTY_001/metrics?date=2026-03-03")

        assert response.status_code == 200
        body = response.json()
        assert body["unique_visitors"] == 0
        assert body["converted_visitors"] == 0
        assert body["conversion_rate"] == 0.0
        assert body["avg_dwell_per_zone"] == {}
        assert body["queue_depth"] == 0
        assert body["abandonment_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_metrics_zero_purchases(self, client):
        events = [
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_no_buy",
                "event_type": "ENTRY",
                "timestamp": "2026-03-04T10:00:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            }
        ]
        await client.post("/events/ingest", json={"events": events})
        response = await client.get("/stores/STORE_BLR_002/metrics?date=2026-03-04")

        body = response.json()
        assert body["unique_visitors"] == 1
        assert body["converted_visitors"] == 0
        assert body["conversion_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_metrics_excludes_staff_from_visitor_count(self, client):
        events = [
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_staff",
                "event_type": "ENTRY",
                "timestamp": "2026-03-03T09:00:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": True,
                "confidence": 0.95,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_customer",
                "event_type": "ENTRY",
                "timestamp": "2026-03-03T09:05:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
        ]
        await client.post("/events/ingest", json={"events": events})
        response = await client.get("/stores/STORE_BLR_002/metrics?date=2026-03-03")

        assert response.json()["unique_visitors"] == 1

    @pytest.mark.asyncio
    async def test_metrics_abandonment_rate(self, client):
        events = [
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_a",
                "event_type": "ENTRY",
                "timestamp": "2026-03-05T10:00:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_BILLING_01",
                "visitor_id": "VIS_a",
                "event_type": "BILLING_QUEUE_JOIN",
                "timestamp": "2026-03-05T10:10:00Z",
                "zone_id": "BILLING",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {"queue_depth": 2},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_BILLING_01",
                "visitor_id": "VIS_a",
                "event_type": "BILLING_QUEUE_ABANDON",
                "timestamp": "2026-03-05T10:12:00Z",
                "zone_id": "BILLING",
                "dwell_ms": 0,
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
                "timestamp": "2026-03-05T10:01:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_BILLING_01",
                "visitor_id": "VIS_b",
                "event_type": "BILLING_QUEUE_JOIN",
                "timestamp": "2026-03-05T10:11:00Z",
                "zone_id": "BILLING",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {"queue_depth": 1},
            },
        ]
        await client.post("/events/ingest", json={"events": events})
        response = await client.get("/stores/STORE_BLR_002/metrics?date=2026-03-05")

        body = response.json()
        assert body["abandonment_rate"] == 0.5
        assert body["queue_depth"] == 1

    @pytest.mark.asyncio
    async def test_metrics_database_unavailable_returns_503(self, client):
        with patch("app.routes.metrics.compute_store_metrics", side_effect=OperationalError("", {}, Exception())):
            response = await client.get("/stores/STORE_BLR_002/metrics")

        assert response.status_code == 503


class TestPosLoader:
    def test_load_pos_transactions(self, use_test_pos_file):
        from app.pos import get_store_transactions_for_date, load_pos_transactions

        txns = load_pos_transactions(POS_FIXTURE)
        assert len(txns) == 3
        store_txns = get_store_transactions_for_date("STORE_BLR_002", date(2026, 3, 3), POS_FIXTURE)
        assert len(store_txns) == 2
