from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def clip_timestamp(clip_start: datetime, frame_index: int, fps: float) -> datetime:
    offset = timedelta(seconds=frame_index / fps)
    ts = clip_start + offset
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class EventEmitter:
    """Builds schema-compliant events."""

    def __init__(
        self,
        store_id: str,
        camera_id: str,
        clip_start: datetime,
        fps: float,
    ) -> None:
        self.store_id = store_id
        self.camera_id = camera_id
        self.clip_start = clip_start
        self.fps = fps
        self.events: list[dict[str, Any]] = []

    def _base(
        self,
        visitor_id: str,
        event_type: str,
        frame_index: int,
        confidence: float,
        session_seq: int,
        is_staff: bool,
        zone_id: str | None = None,
        dwell_ms: int = 0,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        return {
            "event_id": str(uuid4()),
            "store_id": self.store_id,
            "camera_id": self.camera_id,
            "visitor_id": visitor_id,
            "event_type": event_type,
            "timestamp": format_timestamp(self.timestamp_for_frame(frame_index)),
            "zone_id": zone_id,
            "dwell_ms": dwell_ms,
            "is_staff": is_staff,
            "confidence": round(confidence, 2),
            "metadata": metadata or {},
        }

    def timestamp_for_frame(self, frame_index: int) -> datetime:
        return clip_timestamp(self.clip_start, frame_index, self.fps)

    def emit_entry(
        self,
        visitor_id: str,
        frame_index: int,
        confidence: float,
        session_seq: int,
        is_staff: bool,
        reentry: bool = False,
    ) -> dict[str, Any]:
        event = self._base(
            visitor_id,
            "REENTRY" if reentry else "ENTRY",
            frame_index,
            confidence,
            session_seq,
            is_staff,
        )
        event["metadata"]["session_seq"] = session_seq
        self.events.append(event)
        return event

    def emit_exit(
        self,
        visitor_id: str,
        frame_index: int,
        confidence: float,
        session_seq: int,
        is_staff: bool,
    ) -> dict[str, Any]:
        event = self._base(
            visitor_id,
            "EXIT",
            frame_index,
            confidence,
            session_seq,
            is_staff,
        )
        event["metadata"]["session_seq"] = session_seq
        self.events.append(event)
        return event

    def emit_zone_enter(
        self,
        visitor_id: str,
        frame_index: int,
        confidence: float,
        session_seq: int,
        is_staff: bool,
        zone_id: str,
        sku_zone: str | None,
    ) -> dict[str, Any]:
        event = self._base(
            visitor_id,
            "ZONE_ENTER",
            frame_index,
            confidence,
            session_seq,
            is_staff,
            zone_id=zone_id,
            metadata={"sku_zone": sku_zone, "session_seq": session_seq},
        )
        self.events.append(event)
        return event

    def emit_zone_exit(
        self,
        visitor_id: str,
        frame_index: int,
        confidence: float,
        session_seq: int,
        is_staff: bool,
        zone_id: str,
    ) -> dict[str, Any]:
        event = self._base(
            visitor_id,
            "ZONE_EXIT",
            frame_index,
            confidence,
            session_seq,
            is_staff,
            zone_id=zone_id,
            metadata={"session_seq": session_seq},
        )
        self.events.append(event)
        return event

    def emit_zone_dwell(
        self,
        visitor_id: str,
        frame_index: int,
        confidence: float,
        session_seq: int,
        is_staff: bool,
        zone_id: str,
        dwell_ms: int,
        sku_zone: str | None,
    ) -> dict[str, Any]:
        event = self._base(
            visitor_id,
            "ZONE_DWELL",
            frame_index,
            confidence,
            session_seq,
            is_staff,
            zone_id=zone_id,
            dwell_ms=dwell_ms,
            metadata={"sku_zone": sku_zone, "session_seq": session_seq},
        )
        self.events.append(event)
        return event

    def emit_billing_queue_join(
        self,
        visitor_id: str,
        frame_index: int,
        confidence: float,
        session_seq: int,
        is_staff: bool,
        queue_depth: int,
    ) -> dict[str, Any]:
        event = self._base(
            visitor_id,
            "BILLING_QUEUE_JOIN",
            frame_index,
            confidence,
            session_seq,
            is_staff,
            zone_id="BILLING",
            metadata={"queue_depth": queue_depth, "session_seq": session_seq},
        )
        self.events.append(event)
        return event

    def emit_billing_queue_abandon(
        self,
        visitor_id: str,
        frame_index: int,
        confidence: float,
        session_seq: int,
        is_staff: bool,
    ) -> dict[str, Any]:
        event = self._base(
            visitor_id,
            "BILLING_QUEUE_ABANDON",
            frame_index,
            confidence,
            session_seq,
            is_staff,
            zone_id="BILLING",
            metadata={"session_seq": session_seq},
        )
        self.events.append(event)
        return event


def write_events_jsonl(events: list[dict[str, Any]], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")
    return path


def load_events_jsonl(path: str | Path) -> list[dict[str, Any]]:
    events = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events
