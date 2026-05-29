from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from pipeline.emit import load_events_jsonl


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def sort_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(events, key=lambda item: parse_timestamp(item["timestamp"]))


def compute_delay_seconds(
    event_index: int,
    events: list[dict[str, Any]],
    speed_multiplier: float,
) -> float:
    if event_index == 0:
        return 0.0
    prev = parse_timestamp(events[event_index - 1]["timestamp"])
    curr = parse_timestamp(events[event_index]["timestamp"])
    delta = (curr - prev).total_seconds()
    return max(0.0, delta / speed_multiplier)


async def stream_events_to_api(
    events: list[dict[str, Any]],
    api_url: str,
    speed_multiplier: float = 120.0,
) -> int:
    """Ingest events on a simulated timeline (120× = 20 min clip in ~10 s)."""
    ordered = sort_events(events)
    if not ordered:
        return 0

    sent = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        for index, event in enumerate(ordered):
            delay = compute_delay_seconds(index, ordered, speed_multiplier)
            if delay > 0:
                await asyncio.sleep(delay)
            response = await client.post(
                f"{api_url.rstrip('/')}/events/ingest",
                json={"events": [event]},
            )
            response.raise_for_status()
            sent += 1
    return sent


def stream_events_to_api_sync(
    events: list[dict[str, Any]],
    api_url: str,
    speed_multiplier: float = 120.0,
) -> int:
    ordered = sort_events(events)
    if not ordered:
        return 0

    sent = 0
    with httpx.Client(timeout=30.0) as client:
        for index, event in enumerate(ordered):
            delay = compute_delay_seconds(index, ordered, speed_multiplier)
            if delay > 0:
                time.sleep(delay)
            response = client.post(
                f"{api_url.rstrip('/')}/events/ingest",
                json={"events": [event]},
            )
            response.raise_for_status()
            sent += 1
    return sent


async def main_async(
    source: str,
    api_url: str,
    speed: float,
    store_id: str | None,
) -> int:
    events = load_events_jsonl(source)
    if store_id:
        events = [event for event in events if event.get("store_id") == store_id]
    count = await stream_events_to_api(events, api_url, speed)
    print(f"Streamed {count} events to {api_url} at {speed}× speed")
    return count
