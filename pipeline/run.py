from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from pipeline.config import PipelineSettings
from pipeline.detect import discover_clips, process_video_file
from pipeline.emit import write_events_jsonl
from pipeline.layout import infer_store_camera_from_filename, load_store_layout
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


def run_video_mode(settings: PipelineSettings, args: argparse.Namespace) -> list[dict]:
    layout = load_store_layout(settings.layout_path)
    clips = discover_clips(settings.clips_dir)
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
