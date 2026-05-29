from __future__ import annotations

from pathlib import Path

from pipeline.emit import load_events_jsonl, write_events_jsonl


def replay_events(
    source_path: str | Path,
    output_path: str | Path,
    store_id: str | None = None,
) -> list[dict]:
    """Copy/normalize pre-built events — useful for CI and API integration tests."""
    events = load_events_jsonl(source_path)
    if store_id:
        events = [event for event in events if event.get("store_id") == store_id]
    write_events_jsonl(events, output_path)
    return events
