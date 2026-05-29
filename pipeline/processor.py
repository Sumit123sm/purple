from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pipeline.config import PipelineSettings
from pipeline.emit import EventEmitter
from pipeline.tracker import SessionManager, TrackState, build_track_signature, estimate_staff_from_crop
from pipeline.zones import crossed_entry_line, crossed_entry_line_x, zones_at_point


@dataclass
class Detection:
    track_id: int
    cx: float
    cy: float
    confidence: float
    crop: Any | None = None


@dataclass
class FramePacket:
    frame_index: int
    detections: list[Detection]


class ClipProcessor:
    """Converts per-frame detections into behavioural events."""

    def __init__(
        self,
        store_id: str,
        camera_id: str,
        camera_config: dict[str, Any],
        clip_start: datetime,
        settings: PipelineSettings | None = None,
    ) -> None:
        self.store_id = store_id
        self.camera_id = camera_id
        self.camera_config = camera_config
        self.settings = settings or PipelineSettings()
        fps = camera_config.get("fps") or self.settings.default_fps
        self.emitter = EventEmitter(store_id, camera_id, clip_start, fps)
        self.session_manager = SessionManager(self.settings.reentry_window_seconds)
        self.tracks: dict[int, TrackState] = {}
        self.zone_defs = camera_config.get("zones") or []
        self.entry_line = camera_config.get("entry_line")
        self.camera_type = camera_config.get("type", "floor")

    def process_frames(self, frames: list[FramePacket]) -> list[dict]:
        for packet in frames:
            self._process_frame(packet)
        return self.emitter.events

    def _process_frame(self, packet: FramePacket) -> None:
        seen_ids = set()
        billing_count = 0

        for det in packet.detections:
            seen_ids.add(det.track_id)
            track = self.tracks.get(det.track_id)
            if track is None:
                track = TrackState(track_id=det.track_id)
                self.tracks[det.track_id] = track

            prev_cx, prev_cy = track.last_cx, track.last_cy
            track.last_cx, track.last_cy = det.cx, det.cy
            track.signature = build_track_signature(det.cx, det.cy, det.track_id)

            if not track.is_staff and det.crop is not None:
                track.is_staff, staff_conf = estimate_staff_from_crop(det.crop)
            confidence = det.confidence if not track.is_staff else max(det.confidence, 0.8)

            if self.entry_line and track.visitor_id is None:
                crossing = self._check_entry_crossing(prev_cx, prev_cy, det.cx, det.cy)
                if crossing == "ENTRY":
                    self._start_visit(track, packet.frame_index, confidence, det)
                elif crossing == "EXIT" and track.visitor_id:
                    self._end_visit(track, packet.frame_index, confidence)

            if track.visitor_id:
                self._update_zones(track, packet.frame_index, confidence, det.cx, det.cy)

            if any(zone["zone_id"] == "BILLING" for zone in zones_at_point(det.cx, det.cy, self.zone_defs)):
                billing_count += 1

        for track_id, track in list(self.tracks.items()):
            if track_id not in seen_ids and track.active and track.visitor_id and not track.exited:
                if self.camera_type == "entry" and self.entry_line:
                    self._end_visit(track, packet.frame_index, 0.6)
                track.active = False

        self._update_billing_queue(packet.frame_index, billing_count)

    def _check_entry_crossing(
        self,
        prev_x: float,
        prev_y: float,
        curr_x: float,
        curr_y: float,
    ) -> str | None:
        if not self.entry_line:
            return None
        axis = self.entry_line.get("axis", "y")
        position = float(self.entry_line["position"])
        direction = self.entry_line.get("inbound_direction", "down")
        if axis == "x":
            return crossed_entry_line_x(prev_x, curr_x, position, direction)
        return crossed_entry_line(prev_y, curr_y, position, direction)

    def _start_visit(
        self,
        track: TrackState,
        frame_index: int,
        confidence: float,
        det: Detection,
    ) -> None:
        event_time = self.emitter.timestamp_for_frame(frame_index)
        reentry_id = self.session_manager.match_reentry(track.signature, event_time)
        if reentry_id:
            track.visitor_id = reentry_id
            track.session_seq += 1
            track.exited = False
            track.active = True
            self.emitter.emit_entry(
                track.visitor_id,
                frame_index,
                confidence,
                track.session_seq,
                track.is_staff,
                reentry=True,
            )
            return

        track.visitor_id = self.session_manager.new_visitor_id()
        track.session_seq = 1
        track.exited = False
        track.active = True
        self.emitter.emit_entry(
            track.visitor_id,
            frame_index,
            confidence,
            track.session_seq,
            track.is_staff,
        )

    def _end_visit(self, track: TrackState, frame_index: int, confidence: float) -> None:
        if not track.visitor_id or track.exited:
            return
        for zone_id in list(track.current_zones):
            self._leave_zone(track, zone_id, frame_index, confidence)
        if track.in_billing_queue:
            self.emitter.emit_billing_queue_abandon(
                track.visitor_id,
                frame_index,
                confidence,
                track.session_seq,
                track.is_staff,
            )
            track.in_billing_queue = False

        self.emitter.emit_exit(
            track.visitor_id,
            frame_index,
            confidence,
            track.session_seq,
            track.is_staff,
        )
        self.session_manager.register_exit(
            track.visitor_id,
            self.emitter.timestamp_for_frame(frame_index),
            track.signature,
        )
        track.exited = True
        track.active = False

    def _update_zones(
        self,
        track: TrackState,
        frame_index: int,
        confidence: float,
        cx: float,
        cy: float,
    ) -> None:
        matched = {zone["zone_id"]: zone for zone in zones_at_point(cx, cy, self.zone_defs)}
        entered = set(matched) - track.current_zones
        exited = track.current_zones - set(matched)

        for zone_id in entered:
            zone = matched[zone_id]
            now = self.emitter.timestamp_for_frame(frame_index)
            track.zone_entered_at[zone_id] = now
            track.last_dwell_emit[zone_id] = now
            self.emitter.emit_zone_enter(
                track.visitor_id,
                frame_index,
                confidence,
                track.session_seq,
                track.is_staff,
                zone_id,
                zone.get("sku_zone"),
            )

        for zone_id in exited:
            self._leave_zone(track, zone_id, frame_index, confidence)

        track.current_zones = set(matched)

        for zone_id in track.current_zones:
            entered_at = track.zone_entered_at.get(zone_id)
            last_emit = track.last_dwell_emit.get(zone_id)
            if not entered_at or not last_emit:
                continue
            now = self.emitter.timestamp_for_frame(frame_index)
            if (now - last_emit).total_seconds() * 1000 >= self.settings.dwell_emit_interval_ms:
                dwell_ms = int((now - entered_at).total_seconds() * 1000)
                zone = matched[zone_id]
                self.emitter.emit_zone_dwell(
                    track.visitor_id,
                    frame_index,
                    confidence,
                    track.session_seq,
                    track.is_staff,
                    zone_id,
                    dwell_ms,
                    zone.get("sku_zone"),
                )
                track.last_dwell_emit[zone_id] = now

    def _leave_zone(
        self,
        track: TrackState,
        zone_id: str,
        frame_index: int,
        confidence: float,
    ) -> None:
        if zone_id not in track.current_zones:
            return
        self.emitter.emit_zone_exit(
            track.visitor_id,
            frame_index,
            confidence,
            track.session_seq,
            track.is_staff,
            zone_id,
        )
        track.current_zones.discard(zone_id)
        track.zone_entered_at.pop(zone_id, None)
        track.last_dwell_emit.pop(zone_id, None)

        if zone_id == "BILLING" and track.in_billing_queue:
            self.emitter.emit_billing_queue_abandon(
                track.visitor_id,
                frame_index,
                confidence,
                track.session_seq,
                track.is_staff,
            )
            track.in_billing_queue = False

    def _update_billing_queue(self, frame_index: int, billing_count: int) -> None:
        if billing_count <= 0:
            return
        queue_depth = max(0, billing_count - 1)
        for track in self.tracks.values():
            if not track.visitor_id or track.is_staff:
                continue
            if "BILLING" not in track.current_zones:
                continue
            if track.in_billing_queue or queue_depth <= 0:
                continue
            track.in_billing_queue = True
            self.emitter.emit_billing_queue_join(
                track.visitor_id,
                frame_index,
                0.75,
                track.session_seq,
                track.is_staff,
                queue_depth,
            )
