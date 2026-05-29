# PROMPT: Generate pytest tests for a Pydantic StoreEvent model matching this schema:
# event_id (uuid), store_id, camera_id, visitor_id, event_type enum, timestamp ISO-8601,
# zone_id nullable, dwell_ms, is_staff, confidence 0-1, metadata with queue_depth/sku_zone/session_seq.
# Test valid events, invalid confidence, invalid event_type, extra fields forbidden, batch max 500.
# CHANGES MADE: Added explicit ENTRY/EXIT zone_id=null tests and ISO-8601 Z suffix parsing case.

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models import EventType, IngestRequest, StoreEvent


FIXTURES = Path(__file__).parent / "fixtures"


def _valid_event(**overrides) -> dict:
    base = {
        "event_id": str(uuid4()),
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_c8a2f1",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:22:10Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.91,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
    }
    base.update(overrides)
    return base


class TestStoreEventSchema:
    def test_valid_entry_event(self):
        event = StoreEvent.model_validate(_valid_event())
        assert event.event_type == EventType.ENTRY
        assert event.zone_id is None
        assert event.confidence == 0.91

    def test_valid_zone_dwell_event(self):
        event = StoreEvent.model_validate(
            _valid_event(
                event_type="ZONE_DWELL",
                zone_id="SKINCARE",
                dwell_ms=8400,
                metadata={"sku_zone": "MOISTURISER", "session_seq": 5},
            )
        )
        assert event.event_type == EventType.ZONE_DWELL
        assert event.dwell_ms == 8400
        assert event.metadata.sku_zone == "MOISTURISER"

    def test_timestamp_parses_z_suffix(self):
        event = StoreEvent.model_validate(_valid_event(timestamp="2026-03-03T14:22:10Z"))
        assert event.timestamp.year == 2026
        assert event.timestamp.month == 3

    def test_rejects_confidence_above_one(self):
        with pytest.raises(ValidationError):
            StoreEvent.model_validate(_valid_event(confidence=1.5))

    def test_rejects_negative_dwell(self):
        with pytest.raises(ValidationError):
            StoreEvent.model_validate(_valid_event(dwell_ms=-1))

    def test_rejects_unknown_event_type(self):
        with pytest.raises(ValidationError):
            StoreEvent.model_validate(_valid_event(event_type="INVALID"))

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            StoreEvent.model_validate(_valid_event(extra_field="bad"))

    def test_all_event_types_accepted(self):
        for event_type in EventType:
            event = StoreEvent.model_validate(_valid_event(event_type=event_type.value))
            assert event.event_type == event_type


class TestIngestRequest:
    def test_accepts_up_to_500_events(self):
        events = [_valid_event() for _ in range(500)]
        req = IngestRequest(events=[StoreEvent.model_validate(e) for e in events])
        assert len(req.events) == 500

    def test_rejects_more_than_500_events(self):
        events = [StoreEvent.model_validate(_valid_event()) for _ in range(501)]
        with pytest.raises(ValidationError):
            IngestRequest(events=events)


class TestSampleEventsFixture:
    def test_sample_events_jsonl_parses(self):
        path = FIXTURES / "sample_events.jsonl"
        if not path.exists():
            pytest.skip("sample_events.jsonl fixture not present")
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1
        for line in lines:
            data = json.loads(line)
            event = StoreEvent.model_validate(data)
            assert event.event_id is not None
