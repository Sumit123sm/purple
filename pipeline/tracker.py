from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class ExitedVisitor:
    visitor_id: str
    exited_at: datetime
    signature: str


@dataclass
class TrackState:
    track_id: int
    visitor_id: str | None = None
    session_seq: int = 0
    is_staff: bool = False
    active: bool = True
    exited: bool = False
    last_cx: float = 0.0
    last_cy: float = 0.0
    current_zones: set[str] = field(default_factory=set)
    zone_entered_at: dict[str, datetime] = field(default_factory=dict)
    last_dwell_emit: dict[str, datetime] = field(default_factory=dict)
    in_billing_queue: bool = False
    signature: str = ""


class SessionManager:
    """Assigns visitor tokens and handles re-entry detection."""

    def __init__(self, reentry_window_seconds: int = 1800) -> None:
        self.reentry_window_seconds = reentry_window_seconds
        self._next_token = 1
        self._exited: list[ExitedVisitor] = []

    def new_visitor_id(self) -> str:
        # Use UUIDv4-based token to avoid weak-hash security warnings
        token = f"VIS_{uuid.uuid4().hex[:8]}"
        self._next_token += 1
        return token

    def register_exit(self, visitor_id: str, exited_at: datetime, signature: str) -> None:
        self._exited.append(ExitedVisitor(visitor_id, exited_at, signature))
        self._prune_exited(exited_at)

    def match_reentry(self, signature: str, event_time: datetime) -> str | None:
        self._prune_exited(event_time)
        for record in reversed(self._exited):
            if record.signature != signature:
                continue
            delta = (event_time - record.exited_at).total_seconds()
            if 0 <= delta <= self.reentry_window_seconds:
                self._exited = [item for item in self._exited if item.visitor_id != record.visitor_id]
                return record.visitor_id
        return None

    def _prune_exited(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.reentry_window_seconds)
        self._exited = [item for item in self._exited if item.exited_at >= cutoff]


def build_track_signature(cx: float, cy: float, track_id: int) -> str:
    """Lightweight re-id signature from normalized position + track seed."""
    bucket_x = int(cx * 20)
    bucket_y = int(cy * 20)
    return f"{bucket_x}:{bucket_y}:{track_id % 997}"


def estimate_staff_from_crop(crop) -> tuple[bool, float]:
    """Heuristic staff uniform detection using hue in upper body region."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return False, 0.5

    if crop is None or crop.size == 0:
        return False, 0.5

    height = crop.shape[0]
    upper = crop[0 : max(1, int(height * 0.45))]
    hsv = cv2.cvtColor(upper, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    saturation = hsv[:, :, 1]
    mask = saturation > 60
    if not mask.any():
        return False, 0.55

    avg_hue = float(hue[mask].mean())
    # Staff uniforms often green/teal in challenge footage.
    is_staff = 35 <= avg_hue <= 85
    confidence = 0.82 if is_staff else 0.68
    return is_staff, confidence
