# PROMPT: Write pytest tests for GET /stores/{id}/funnel with session-based stages:
# entry, zone_visit, billing_queue, purchase. Include drop-off %, staff exclusion,
# empty store, re-entry as separate session (not double ENTRY), and POS purchase correlation.
# CHANGES MADE: Added explicit drop-off math test and REENTRY-vs-duplicate-ENTRY session test.

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

    settings = Settings(pos_transactions_path=str(POS_FIXTURE))
    monkeypatch.setattr("app.config.settings", settings)
    monkeypatch.setattr("app.pos.settings", settings)


class TestStoreFunnelEndpoint:
    @pytest.mark.asyncio
    async def test_funnel_with_sample_events(self, client, sample_events_from_file):
        await client.post("/events/ingest", json={"events": sample_events_from_file})
        response = await client.get("/stores/STORE_BLR_002/funnel?date=2026-03-03")

        assert response.status_code == 200
        body = response.json()
        assert body["store_id"] == "STORE_BLR_002"
        assert body["total_sessions"] == 1

        stages = {stage["stage"]: stage for stage in body["stages"]}
        assert stages["entry"]["count"] == 1
        assert stages["zone_visit"]["count"] == 1
        assert stages["billing_queue"]["count"] == 1
        assert stages["purchase"]["count"] == 1
        assert stages["entry"]["drop_off_pct"] == 0.0
        assert stages["zone_visit"]["drop_off_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_funnel_empty_store(self, client):
        response = await client.get("/stores/STORE_EMPTY_001/funnel?date=2026-03-03")

        assert response.status_code == 200
        body = response.json()
        assert body["total_sessions"] == 0
        assert all(stage["count"] == 0 for stage in body["stages"])
        assert all(stage["drop_off_pct"] == 0.0 for stage in body["stages"])

    @pytest.mark.asyncio
    async def test_funnel_drop_off_between_stages(self, client):
        events = [
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_full",
                "event_type": "ENTRY",
                "timestamp": "2026-03-06T10:00:00Z",
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
                "visitor_id": "VIS_full",
                "event_type": "ZONE_ENTER",
                "timestamp": "2026-03-06T10:05:00Z",
                "zone_id": "SKINCARE",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_browse_only",
                "event_type": "ENTRY",
                "timestamp": "2026-03-06T10:01:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
        ]
        await client.post("/events/ingest", json={"events": events})
        response = await client.get("/stores/STORE_BLR_002/funnel?date=2026-03-06")

        stages = {stage["stage"]: stage for stage in response.json()["stages"]}
        assert stages["entry"]["count"] == 2
        assert stages["zone_visit"]["count"] == 1
        assert stages["zone_visit"]["drop_off_pct"] == 50.0
        assert stages["billing_queue"]["count"] == 0
        assert stages["billing_queue"]["drop_off_pct"] == 100.0

    @pytest.mark.asyncio
    async def test_funnel_reentry_is_separate_session(self, client):
        events = [
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_returner",
                "event_type": "ENTRY",
                "timestamp": "2026-03-07T10:00:00Z",
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
                "visitor_id": "VIS_returner",
                "event_type": "BILLING_QUEUE_JOIN",
                "timestamp": "2026-03-07T10:20:00Z",
                "zone_id": "BILLING",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {"queue_depth": 1},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_returner",
                "event_type": "EXIT",
                "timestamp": "2026-03-07T10:30:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_returner",
                "event_type": "REENTRY",
                "timestamp": "2026-03-07T11:00:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_returner",
                "event_type": "EXIT",
                "timestamp": "2026-03-07T11:05:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
        ]
        await client.post("/events/ingest", json={"events": events})
        response = await client.get("/stores/STORE_BLR_002/funnel?date=2026-03-07")

        body = response.json()
        stages = {stage["stage"]: stage for stage in body["stages"]}
        assert body["total_sessions"] == 2
        assert stages["entry"]["count"] == 2
        assert stages["billing_queue"]["count"] == 1
        assert stages["purchase"]["count"] == 0

    @pytest.mark.asyncio
    async def test_funnel_excludes_staff_sessions(self, client):
        events = [
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_staff",
                "event_type": "ENTRY",
                "timestamp": "2026-03-08T09:00:00Z",
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
                "timestamp": "2026-03-08T09:05:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
        ]
        await client.post("/events/ingest", json={"events": events})
        response = await client.get("/stores/STORE_BLR_002/funnel?date=2026-03-08")

        body = response.json()
        assert body["total_sessions"] == 1
        assert body["stages"][0]["count"] == 1

    @pytest.mark.asyncio
    async def test_funnel_database_unavailable_returns_503(self, client):
        with patch("app.routes.funnel.compute_store_funnel", side_effect=OperationalError("", {}, Exception())):
            response = await client.get("/stores/STORE_BLR_002/funnel")

        assert response.status_code == 503


class TestSessionBuilder:
    def test_reentry_starts_new_session_not_extra_entry(self):
        from app.sessions import build_sessions
        from app.tables import EventRecord

        def make(event_type, ts, visitor="VIS_1"):
            return EventRecord(
                event_id=str(uuid4()),
                store_id="STORE_BLR_002",
                camera_id="CAM_ENTRY_01",
                visitor_id=visitor,
                event_type=event_type,
                timestamp=__import__("datetime").datetime.fromisoformat(ts.replace("Z", "+00:00")),
                zone_id=None,
                dwell_ms=0,
                is_staff=False,
                confidence=0.9,
                metadata_json="{}",
            )

        events = [
            make("ENTRY", "2026-03-03T10:00:00Z"),
            make("EXIT", "2026-03-03T10:30:00Z"),
            make("REENTRY", "2026-03-03T11:00:00Z"),
            make("EXIT", "2026-03-03T11:15:00Z"),
        ]
        sessions = build_sessions(events)
        assert len(sessions) == 2
        assert sessions[0].start_event_type == "ENTRY"
        assert sessions[1].start_event_type == "REENTRY"
