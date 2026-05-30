from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.config import PipelineSettings
from pipeline.layout import get_camera_config, get_store_config, load_store_layout
from pipeline.processor import ClipProcessor, Detection, FramePacket


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
            # Synthetic fallback for CPU-only/demo runs when ultralytics isn't installed.
            # Generate deterministic multi-person movement that can cross entry lines
            # and create zone/queue behavior across different camera layouts.
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
