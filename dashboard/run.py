from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

# When `dashboard/run.py` is executed as a script (e.g. `python dashboard/run.py`),
# Python does not automatically add the project root to `sys.path`, which makes
# `from dashboard...` imports fail with ModuleNotFoundError. Ensure the repo
# root is on `sys.path` so the package imports work whether the module is run
# as `python -m dashboard.run` or `python dashboard/run.py`.
if __package__ is None:  # running as a script
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

from dashboard.stream_replay import main_async


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live dashboard event streamer")
    parser.add_argument("--source", default="tests/fixtures/sample_events.jsonl")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--speed", type=float, default=120.0, help="Simulated realtime multiplier")
    parser.add_argument("--store-id", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(args.source)
    if not source.exists():
        print(f"Source not found: {source}", file=sys.stderr)
        return 1

    print(f"Streaming {source} -> {args.api_url} ({args.speed}x speed)")
    print(f"Open dashboard: {args.api_url}/dashboard?store_id=STORE_BLR_002&date=2026-03-03")

    try:
        asyncio.run(main_async(str(source), args.api_url, args.speed, args.store_id))
    except httpx.HTTPError as exc:
        print(f"Stream failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Stream failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
