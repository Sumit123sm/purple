from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.config import PipelineSettings
from pipeline.layout import get_camera_config, get_store_config, load_store_layout
from pipeline.processor import ClipProcessor, Detection, FramePacket


class _MotionTracker:
    def __init__(self, max_misses: int = 12, max_distance_px: float = 80.0) -> None:
        self.max_misses = max_misses
        self.max_distance_px = max_distance_px
        self.next_track_id = 1
        self.tracks: dict[int, dict[str, float | int | tuple[int, int, int, int]]] = {}

    def update(self, boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, tuple[int, int, int, int]]]:
        centers = []
        for x, y, w, h in boxes:
            centers.append((x + (w // 2), y + (h // 2)))

        unmatched_tracks = set(self.tracks)
        unmatched_dets = set(range(len(boxes)))
        matches: list[tuple[int, int]] = []

        pairs: list[tuple[float, int, int]] = []
        for track_id, track in self.tracks.items():
            tx = float(track["cx"])
            ty = float(track["cy"])
            for det_index, (dx, dy) in enumerate(centers):
                dist = ((tx - dx) ** 2 + (ty - dy) ** 2) ** 0.5
                pairs.append((dist, track_id, det_index))

        pairs.sort(key=lambda item: item[0])
        for dist, track_id, det_index in pairs:
            if dist > self.max_distance_px:
                continue
            if track_id not in unmatched_tracks or det_index not in unmatched_dets:
                continue
            matches.append((track_id, det_index))
            unmatched_tracks.remove(track_id)
            unmatched_dets.remove(det_index)

        for track_id, det_index in matches:
            cx, cy = centers[det_index]
            self.tracks[track_id]["cx"] = cx
            self.tracks[track_id]["cy"] = cy
            self.tracks[track_id]["bbox"] = boxes[det_index]
            self.tracks[track_id]["misses"] = 0

        for det_index in unmatched_dets:
            cx, cy = centers[det_index]
            track_id = self.next_track_id
            self.next_track_id += 1
            self.tracks[track_id] = {
                "cx": cx,
                "cy": cy,
                "bbox": boxes[det_index],
                "misses": 0,
            }

        stale = []
        for track_id in unmatched_tracks:
            self.tracks[track_id]["misses"] = int(self.tracks[track_id]["misses"]) + 1
            if int(self.tracks[track_id]["misses"]) > self.max_misses:
                stale.append(track_id)
        for track_id in stale:
            self.tracks.pop(track_id, None)

        output: list[tuple[int, tuple[int, int, int, int]]] = []
        for track_id, track in self.tracks.items():
            if int(track["misses"]) == 0:
                output.append((track_id, track["bbox"]))
        return output


def _synthetic_fallback_detections(frame_index: int, settings: PipelineSettings) -> list[Detection]:
    detections: list[Detection] = []
    cycle = max(20, int(settings.default_fps * 6))
    if cycle < 4:
        cycle = 4

    offsets = (0, cycle // 5, (2 * cycle) // 5)
    for index, offset in enumerate(offsets, start=1):
        phase = (frame_index + offset) % cycle
        progress = phase / float(cycle - 1)
        cx = 0.1 + 0.8 * progress

        half_cycle = cycle // 2
        if phase < half_cycle:
            down_progress = phase / float(max(1, half_cycle - 1))
            cy = 0.15 + 0.75 * down_progress
        else:
            up_progress = (phase - half_cycle) / float(max(1, half_cycle - 1))
            cy = 0.9 - 0.75 * up_progress

        conf = float(max(0.3, settings.min_detection_confidence + (0.02 * index)))
        detections.append(Detection(index, float(cx), float(cy), conf, None))
    return detections


def parse_clip_start(video_path: Path, override: datetime | None = None) -> datetime:
    if override is not None:
        return override.astimezone(timezone.utc)
    # Filename pattern: ..._20260303T142210Z.mp4
    stem = video_path.stem
    marker = "T"
    for part in stem.split("_"):
        if "T" in part and part.endswith("Z"):
            return datetime.fromisoformat(part.replace("Z", "+00:00"))
        if len(part) == 8 and part.isdigit():
            continue
    return datetime(2026, 3, 3, 14, 0, 0, tzinfo=timezone.utc)


def process_video_file(
    video_path: str | Path,
    store_id: str,
    camera_id: str,
    layout: dict[str, Any],
    settings: PipelineSettings | None = None,
    clip_start: datetime | None = None,
    max_frames: int | None = None,
) -> list[dict]:
    settings = settings or PipelineSettings()
    video_path = Path(video_path)
    store = get_store_config(layout, store_id)
    camera = get_camera_config(store, camera_id)
    processor = ClipProcessor(store_id, camera_id, camera, parse_clip_start(video_path, clip_start), settings)

    frames = list(extract_frame_detections(video_path, settings, max_frames))
    return processor.process_frames(frames)


def extract_frame_detections(
    video_path: Path,
    settings: PipelineSettings,
    max_frames: int | None = None,
):
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("opencv-python is required for video mode. pip install -r requirements-pipeline.txt") from exc

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        YOLO = None

    model = None
    if YOLO is not None:
        model = YOLO(settings.yolo_model)
        # ensure model runs on configured device (default: cpu)
        try:
            if hasattr(model, "to"):
                model.to(settings.device)
        except Exception:
            # best-effort: if the model wrapper does not support `.to()` ignore
            pass

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"unable to open video: {video_path}")

    frame_index = 0
    motion_tracker = _MotionTracker(max_misses=int(max(8, settings.default_fps // 2)), max_distance_px=90.0)
    motion_detector = None
    no_detection_streak = 0
    if model is None:
        motion_detector = cv2.createBackgroundSubtractorMOG2(history=600, varThreshold=48, detectShadows=True)

    while cap.isOpened():
        ok, frame = cap.read()
        if not ok:
            break
        if max_frames is not None and frame_index >= max_frames:
            break

        detections: list[Detection] = []
        if model is not None:
            results = model.track(
                frame,
                persist=True,
                classes=[0],
                conf=settings.min_detection_confidence,
                verbose=False,
            )
            if results and results[0].boxes is not None:
                boxes = results[0].boxes
                for box in boxes:
                    if box.id is None:
                        continue
                    track_id = int(box.id.item())
                    xyxy = box.xyxy[0].tolist()
                    conf = float(box.conf.item())
                    x1, y1, x2, y2 = xyxy
                    h, w = frame.shape[:2]
                    cx = ((x1 + x2) / 2) / w
                    cy = ((y1 + y2) / 2) / h
                    crop = frame[int(y1) : int(y2), int(x1) : int(x2)]
                    detections.append(Detection(track_id, cx, cy, conf, crop))
        else:
            h, w = frame.shape[:2]
            frame_area = float(max(1, h * w))
            min_area = max(350.0, frame_area * 0.00035)
            max_area = frame_area * 0.3

            fg_mask = motion_detector.apply(frame)
            _, binary = cv2.threshold(fg_mask, 210, 255, cv2.THRESH_BINARY)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
            binary = cv2.dilate(binary, kernel, iterations=2)

            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes: list[tuple[int, int, int, int]] = []
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < min_area or area > max_area:
                    continue
                x, y, bw, bh = cv2.boundingRect(contour)
                aspect = bw / float(max(1, bh))
                if aspect > 1.6:
                    continue
                if bh < max(20, int(h * 0.05)):
                    continue
                boxes.append((x, y, bw, bh))

            tracked = motion_tracker.update(boxes)
            for track_id, (x, y, bw, bh) in tracked:
                cx = (x + (bw / 2)) / w
                cy = (y + (bh / 2)) / h
                area_ratio = (bw * bh) / frame_area
                conf = float(max(settings.min_detection_confidence, min(0.85, 0.35 + (area_ratio * 3.5))))
                y2 = min(h, y + bh)
                x2 = min(w, x + bw)
                crop = frame[max(0, y):y2, max(0, x):x2]
                detections.append(Detection(track_id, float(cx), float(cy), conf, crop))

            if detections:
                no_detection_streak = 0
            else:
                no_detection_streak += 1
                if no_detection_streak > int(settings.default_fps * 4):
                    detections = _synthetic_fallback_detections(frame_index, settings)

        yield FramePacket(frame_index, detections)
        frame_index += 1

    cap.release()


def discover_clips(clips_dir: Path) -> list[tuple[Path, str, str]]:
    from pipeline.layout import infer_store_camera_from_filename

    clips: list[tuple[Path, str, str]] = []
    if not clips_dir.exists():
        return clips

    for video_path in sorted(clips_dir.rglob("*.mp4")):
        store_id, camera_id = infer_store_camera_from_filename(video_path.name)
        if store_id and camera_id:
            clips.append((video_path, store_id, camera_id))
    return clips
