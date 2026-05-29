#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-replay}"
API_URL="${2:-}"

python -m pipeline.run --mode "$MODE" --output data/events/output.jsonl ${API_URL:+--api-url "$API_URL"}
