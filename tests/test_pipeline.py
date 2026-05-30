# PROMPT: Write pytest tests for the CCTV detection pipeline covering zone geometry,
# entry/exit crossing, re-entry visitor tokens, event schema emission, synthetic
# trajectory processing, and replay mode — without requiring video files or GPU.
# CHANGES MADE: Added ClipProcessor integration test with multi-zone trajectory and
# StoreEvent schema validation on emitted events.

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from app.models import StoreEvent
from pipeline.detect import _MotionTracker
from pipeline.emit import EventEmitter, load_events_jsonl, write_events_jsonl
from pipeline.layout import infer_store_camera_from_filename, load_store_layout
from pipeline.processor import ClipProcessor, Detection, FramePacket
from pipeline.replay import replay_events
from pipeline.tracker import SessionManager, TrackState, build_track_signature
from pipeline.zones import Point, crossed_entry_line, point_in_polygon, zones_at_point

FIXTURES = Path(__file__).parent / "fixtures"
LAYOUT = Path(__file__).parent.parent / "data" / "store_layout.json"


class TestZoneGeometry:
    def test_point_in_polygon(self):
        polygon = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
        assert point_in_polygon(Point(0.5, 0.5), polygon)
        assert not point_in_polygon(Point(1.5, 0.5), polygon)

    def test_entry_line_crossing(self):
        assert crossed_entry_line(0.50, 0.60, 0.55, "down") == "ENTRY"
        assert crossed_entry_line(0.60, 0.50, 0.55, "down") == "EXIT"


class TestSessionManager:
    def test_reentry_matches_signature(self):
        manager = SessionManager(reentry_window_seconds=3600)
        now = datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc)
        signature = build_track_signature(0.5, 0.5, 7)
        visitor_id = manager.new_visitor_id()
        manager.register_exit(visitor_id, now, signature)

        matched = manager.match_reentry(signature, now + timedelta(minutes=10))
        assert matched == visitor_id


class TestEventEmitter:
    def test_emitted_events_validate_against_schema(self):
        clip_start = datetime(2026, 3, 3, 14, 0, tzinfo=timezone.utc)
        emitter = EventEmitter("STORE_BLR_002", "CAM_ENTRY_01", clip_start, fps=15)
        emitter.emit_entry("VIS_abc", frame_index=30, confidence=0.91, session_seq=1, is_staff=False)
        emitter.emit_zone_enter(
            "VIS_abc",
            frame_index=120,
            confidence=0.87,
            session_seq=2,
            is_staff=False,
            zone_id="SKINCARE",
            sku_zone="MOISTURISER",
        )

        for event in emitter.events:
            parsed = StoreEvent.model_validate(event)
            assert isinstance(parsed.event_id, UUID)


class TestClipProcessor:
    def test_synthetic_trajectory_emits_entry_and_zone_events(self):
        layout = load_store_layout(LAYOUT)
        store = next(item for item in layout["stores"] if item["store_id"] == "STORE_BLR_002")
        camera = next(item for item in store["cameras"] if item["camera_id"] == "CAM_FLOOR_01")
        clip_start = datetime(2026, 3, 3, 14, 0, tzinfo=timezone.utc)

        processor = ClipProcessor("STORE_BLR_002", "CAM_FLOOR_01", camera, clip_start)
        processor.tracks[1] = TrackState(track_id=1, visitor_id="VIS_test01", session_seq=1)
        track = processor.tracks[1]

        frames = []
        for frame_index, cx in enumerate(range(10, 30)):
            cy = 0.5
            track.last_cx = (cx - 1) / 100
            track.last_cy = cy
            det = Detection(track_id=1, cx=cx / 100, cy=cy, confidence=0.9)
            frames.append(FramePacket(frame_index, [det]))

        events = processor.process_frames(frames)
        event_types = {event["event_type"] for event in events}
        assert "ZONE_ENTER" in event_types
        assert all(event["visitor_id"] == "VIS_test01" for event in events)


class TestReplayMode:
    def test_replay_writes_jsonl(self, tmp_path):
        source = FIXTURES / "sample_events.jsonl"
        output = tmp_path / "out.jsonl"
        events = replay_events(source, output)
        assert len(events) == 5
        loaded = load_events_jsonl(output)
        assert len(loaded) == 5
        for line in output.read_text(encoding="utf-8").splitlines():
            json.loads(line)


class TestLayoutHelpers:
    def test_infer_store_camera_from_filename(self):
        store_id, camera_id = infer_store_camera_from_filename("STORE_BLR_002_CAM_ENTRY_01.mp4")
        assert store_id == "STORE_BLR_002"
        assert camera_id == "CAM_ENTRY_01"

    def test_zones_at_point(self):
        layout = load_store_layout(LAYOUT)
        store = layout["stores"][0]
        floor = next(cam for cam in store["cameras"] if cam["camera_id"] == "CAM_FLOOR_01")
        zones = zones_at_point(0.2, 0.5, floor["zones"])
        assert zones[0]["zone_id"] == "SKINCARE"


class TestMotionFallbackTracker:
    def test_tracker_keeps_identity_for_nearby_motion(self):
        tracker = _MotionTracker(max_misses=3, max_distance_px=40.0)
        first = tracker.update([(100, 100, 20, 60)])
        assert len(first) == 1
        track_id = first[0][0]

        second = tracker.update([(108, 102, 20, 60)])
        assert len(second) == 1
        assert second[0][0] == track_id

    def test_tracker_drops_stale_tracks_after_misses(self):
        tracker = _MotionTracker(max_misses=1, max_distance_px=40.0)
        tracker.update([(50, 60, 18, 50)])
        tracker.update([])
        tracker.update([])
        assert tracker.tracks == {}
