#!/usr/bin/env bash

# Ensure project root is on PYTHONPATH for imports
export PYTHONPATH="${PYTHONPATH:-.}"

SOURCE=${1:-tests/fixtures/sample_events.jsonl}
API_URL=${2:-http://127.0.0.1:8000}
SPEED=${3:-120.0}

echo "PYTHONPATH=${PYTHONPATH}"
python dashboard/run.py --source "$SOURCE" --api-url "$API_URL" --speed "$SPEED"
