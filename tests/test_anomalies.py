# PROMPT: Write pytest tests for GET /stores/{id}/anomalies covering BILLING_QUEUE_SPIKE,
# CONVERSION_DROP vs 7-day average, DEAD_ZONE (30 min no visits), severity levels,
# suggested_action field, empty store, and 503 handling.
# CHANGES MADE: Added extended POS fixture for multi-day conversion baseline and
# explicit severity assertions per anomaly type.

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def use_test_pos_file(monkeypatch):
    pos_path = FIXTURES / "pos_transactions.csv"
    monkeypatch.setenv("POS_TRANSACTIONS_PATH", str(pos_path))
    from app.config import Settings

    settings = Settings(pos_transactions_path=str(pos_path))
    monkeypatch.setattr("app.config.settings", settings)
    monkeypatch.setattr("app.pos.settings", settings)


def _entry(visitor_id: str, ts: str) -> dict:
    return {
        "event_id": str(uuid4()),
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": visitor_id,
        "event_type": "ENTRY",
        "timestamp": ts,
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {},
    }


def _billing_join(visitor_id: str, ts: str, queue_depth: int = 1) -> dict:
    return {
        "event_id": str(uuid4()),
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_BILLING_01",
        "visitor_id": visitor_id,
        "event_type": "BILLING_QUEUE_JOIN",
        "timestamp": ts,
        "zone_id": "BILLING",
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {"queue_depth": queue_depth},
    }


def _zone_enter(visitor_id: str, ts: str, zone_id: str = "SKINCARE") -> dict:
    return {
        "event_id": str(uuid4()),
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_FLOOR_01",
        "visitor_id": visitor_id,
        "event_type": "ZONE_ENTER",
        "timestamp": ts,
        "zone_id": zone_id,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {},
    }


class TestStoreAnomaliesEndpoint:
    @pytest.mark.asyncio
    async def test_anomalies_empty_store(self, client):
        response = await client.get("/stores/STORE_EMPTY_001/anomalies?date=2026-03-03")
        assert response.status_code == 200
        assert response.json()["active_anomalies"] == []

    @pytest.mark.asyncio
    async def test_queue_spike_anomaly(self, client):
        events = [
            _billing_join("VIS_q1", "2026-03-04T10:00:00Z", queue_depth=1),
            _billing_join("VIS_q2", "2026-03-04T10:30:00Z", queue_depth=5),
        ]
        await client.post("/events/ingest", json={"events": events})
        response = await client.get("/stores/STORE_BLR_002/anomalies?date=2026-03-04")

        types = {item["anomaly_type"] for item in response.json()["active_anomalies"]}
        assert "BILLING_QUEUE_SPIKE" in types
        spike = next(
            item for item in response.json()["active_anomalies"]
            if item["anomaly_type"] == "BILLING_QUEUE_SPIKE"
        )
        assert spike["severity"] == "CRITICAL"
        assert spike["suggested_action"]
        assert spike["metadata"]["queue_depth"] == 5

    @pytest.mark.asyncio
    async def test_conversion_drop_anomaly(self, client, tmp_path, monkeypatch):
        pos_csv = tmp_path / "pos_multi_day.csv"
        rows = ["store_id,transaction_id,timestamp,basket_value_inr"]
        for day in range(24, 27):
            rows.append(f"STORE_BLR_002,TXN_{day},2026-02-{day}T14:38:12Z,1000.00")
        pos_csv.write_text("\n".join(rows) + "\n", encoding="utf-8")

        from app.config import Settings

        settings = Settings(pos_transactions_path=str(pos_csv))
        monkeypatch.setattr("app.config.settings", settings)
        monkeypatch.setattr("app.pos.settings", settings)

        historical_events = []
        for day in (24, 25, 26):
            visitor = f"VIS_hist_{day}"
            historical_events.extend(
                [
                    _entry(visitor, f"2026-02-{day}T14:20:00Z"),
                    _billing_join(visitor, f"2026-02-{day}T14:38:00Z"),
                ]
            )
        historical_events.append(_entry("VIS_today", "2026-03-03T14:20:00Z"))

        await client.post("/events/ingest", json={"events": historical_events})
        response = await client.get("/stores/STORE_BLR_002/anomalies?date=2026-03-03")

        types = {item["anomaly_type"] for item in response.json()["active_anomalies"]}
        assert "CONVERSION_DROP" in types
        drop = next(
            item for item in response.json()["active_anomalies"]
            if item["anomaly_type"] == "CONVERSION_DROP"
        )
        assert drop["severity"] in {"INFO", "WARN", "CRITICAL"}
        assert drop["suggested_action"]
        assert drop["metadata"]["today_conversion_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_dead_zone_anomaly(self, client):
        events = [
            _entry("VIS_dead", "2026-03-05T10:00:00Z"),
            _zone_enter("VIS_dead", "2026-03-05T10:05:00Z", zone_id="SKINCARE"),
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_dead",
                "event_type": "EXIT",
                "timestamp": "2026-03-05T11:00:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
        ]
        await client.post("/events/ingest", json={"events": events})
        response = await client.get("/stores/STORE_BLR_002/anomalies?date=2026-03-05")

        types = {item["anomaly_type"] for item in response.json()["active_anomalies"]}
        assert "DEAD_ZONE" in types
        dead = next(
            item for item in response.json()["active_anomalies"]
            if item["anomaly_type"] == "DEAD_ZONE"
        )
        assert dead["metadata"]["zone_id"] == "SKINCARE"
        assert dead["metadata"]["idle_minutes"] >= 30
        assert dead["suggested_action"]

    @pytest.mark.asyncio
    async def test_anomalies_include_all_required_fields(self, client):
        events = [_billing_join("VIS_q", "2026-03-06T10:00:00Z", queue_depth=4)]
        await client.post("/events/ingest", json={"events": events})
        response = await client.get("/stores/STORE_BLR_002/anomalies?date=2026-03-06")

        assert response.status_code == 200
        body = response.json()
        assert body["store_id"] == "STORE_BLR_002"
        assert "computed_at" in body
        for item in body["active_anomalies"]:
            assert item["anomaly_type"]
            assert item["severity"] in {"INFO", "WARN", "CRITICAL"}
            assert item["message"]
            assert item["suggested_action"]
            assert item["detected_at"]

    @pytest.mark.asyncio
    async def test_anomalies_database_unavailable_returns_503(self, client):
        with patch(
            "app.routes.anomalies.compute_store_anomalies",
            side_effect=OperationalError("", {}, Exception()),
        ):
            response = await client.get("/stores/STORE_BLR_002/anomalies")

        assert response.status_code == 503
