from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from pipeline.config import PipelineSettings
from pipeline.detect import discover_clips, process_video_file
from pipeline.emit import write_events_jsonl
from pipeline.layout import get_store_config, load_store_layout
from pipeline.replay import replay_events


def ingest_to_api(events: list[dict], api_url: str, batch_size: int = 500) -> None:
    if not events:
        print("No events to ingest.")
        return
    with httpx.Client(timeout=60.0) as client:
        for start in range(0, len(events), batch_size):
            batch = events[start : start + batch_size]
            response = client.post(f"{api_url.rstrip('/')}/events/ingest", json={"events": batch})
            response.raise_for_status()
            body = response.json()
            print(
                f"Ingested batch {start // batch_size + 1}: "
                f"accepted={body['accepted']} duplicates={body['duplicates']} rejected={body['rejected']}"
            )


def _load_clip_map(clip_map_path: str | None) -> dict[str, dict[str, str]]:
    if not clip_map_path:
        return {}

    path = Path(clip_map_path)
    if not path.exists():
        raise FileNotFoundError(f"clip map file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    mapping: dict[str, dict[str, str]] = {}

    if isinstance(payload, list):
        for item in payload:
            filename = str(item["filename"]).strip()
            mapping[filename] = {
                "store_id": str(item["store_id"]).strip(),
                "camera_id": str(item["camera_id"]).strip(),
            }
        return mapping

    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, dict):
                mapping[str(key).strip()] = {
                    "store_id": str(value["store_id"]).strip(),
                    "camera_id": str(value["camera_id"]).strip(),
                }
        return mapping

    raise ValueError("clip map must be a JSON list or object")


def _resolve_nonstandard_clips(
    clips_dir: Path,
    layout: dict[str, Any],
    clip_map_path: str | None,
    default_store_id: str | None,
    default_camera_id: str | None,
) -> list[tuple[Path, str, str]]:
    videos = sorted(clips_dir.rglob("*.mp4"))
    if not videos:
        return []

    mapping = _load_clip_map(clip_map_path)
    resolved: list[tuple[Path, str, str]] = []
    unresolved: list[str] = []

    store_camera_cycle: list[str] = []
    if default_store_id and not default_camera_id:
        store_cfg = get_store_config(layout, default_store_id)
        store_camera_cycle = [camera["camera_id"] for camera in store_cfg.get("cameras", [])]

    for index, video_path in enumerate(videos):
        hit = mapping.get(video_path.name)
        if not hit:
            hit = mapping.get(video_path.stem)

        if hit:
            resolved.append((video_path, hit["store_id"], hit["camera_id"]))
            continue

        if default_store_id and default_camera_id:
            resolved.append((video_path, default_store_id, default_camera_id))
            continue

        if default_store_id and store_camera_cycle:
            camera_id = store_camera_cycle[index % len(store_camera_cycle)]
            resolved.append((video_path, default_store_id, camera_id))
            continue

        unresolved.append(video_path.name)

    if unresolved:
        sample = ", ".join(unresolved[:3])
        raise ValueError(
            "Unable to resolve store/camera IDs for clips. "
            "Provide --clip-map or --default-store-id with optional --default-camera-id. "
            f"Unresolved examples: {sample}"
        )

    return resolved


def run_video_mode(settings: PipelineSettings, args: argparse.Namespace) -> list[dict]:
    layout = load_store_layout(settings.layout_path)
    clips = discover_clips(settings.clips_dir)

    if not clips:
        clips = _resolve_nonstandard_clips(
            settings.clips_dir,
            layout,
            args.clip_map,
            args.default_store_id,
            args.default_camera_id,
        )

    if not clips:
        raise FileNotFoundError(
            f"No clips found in {settings.clips_dir}. Place CCTV mp4 files there or use --mode replay."
        )

    all_events: list[dict] = []
    for video_path, store_id, camera_id in clips:
        print(f"Processing {video_path.name} ({store_id}/{camera_id})")
        events = process_video_file(
            video_path,
            store_id,
            camera_id,
            layout,
            settings,
            max_frames=args.max_frames,
        )
        print(f"  -> emitted {len(events)} events")
        all_events.extend(events)

    write_events_jsonl(all_events, settings.output_path)
    return all_events


def run_replay_mode(settings: PipelineSettings, args: argparse.Namespace) -> list[dict]:
    source = Path(args.replay_source or "tests/fixtures/sample_events.jsonl")
    events = replay_events(source, settings.output_path, store_id=args.store_id)
    print(f"Replayed {len(events)} events from {source}")
    return events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Store Intelligence detection pipeline")
    parser.add_argument("--mode", choices=["video", "replay"], default="replay")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="data/events/output.jsonl")
    parser.add_argument("--layout", default="data/store_layout.json")
    parser.add_argument("--clips-dir", default="data/clips")
    parser.add_argument("--replay-source", default="tests/fixtures/sample_events.jsonl")
    parser.add_argument("--store-id", default=None)
    parser.add_argument("--clip-map", default=None, help="JSON mapping for non-standard clip names")
    parser.add_argument("--default-store-id", default=None, help="Fallback store ID for non-standard clip names")
    parser.add_argument("--default-camera-id", default=None, help="Fallback camera ID for all clips when clip names are non-standard")
    parser.add_argument("--device", default="cpu", help="Device to run detection on, e.g. 'cpu' or 'cuda:0'")
    parser.add_argument("--api-url", default=None, help="If set, POST events to running API")
    parser.add_argument("--max-frames", type=int, default=None, help="Limit frames per clip (debug)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = PipelineSettings(
        data_dir=Path(args.data_dir),
        clips_dir=Path(args.clips_dir),
        layout_path=Path(args.layout),
        output_path=Path(args.output),
        device=args.device,
    )

    try:
        if args.mode == "video":
            events = run_video_mode(settings, args)
        else:
            events = run_replay_mode(settings, args)
    except Exception as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {len(events)} events -> {settings.output_path}")

    if args.api_url:
        ingest_to_api(events, args.api_url)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
