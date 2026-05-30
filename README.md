# Store Intelligence System

Purplle Tech Challenge 2026 — Round 2 submission.

## Quick start

```bash
git clone <repo-url> store-intelligence && cd store-intelligence
pip install -r requirements.txt
pytest
docker compose up --build
curl http://localhost:8000/health
```

## Module status

| Module | Status | Description |
|--------|--------|-------------|
| 1 | Done | Foundation, event schema, Docker skeleton, `/health` |
| 2 | Done | Event ingestion (`POST /events/ingest`) — validate, dedup, idempotent |
| 3 | Done | Store metrics (`GET /stores/{id}/metrics`) — visitors, conversion, dwell, queue |
| 4 | Done | Conversion funnel (`GET /stores/{id}/funnel`) — session-based drop-off |
| 5 | Done | Zone heatmap (`GET /stores/{id}/heatmap`) — normalized 0–100 + confidence flag |
| 6 | Done | Anomalies (`GET /stores/{id}/anomalies`) — queue spike, conversion drop, dead zone |
| 7 | Done | Enhanced `/health` — per-store feed status, STALE_FEED warnings |
| 8 | Done | Detection pipeline (`pipeline/`) — YOLO + replay mode |
| 9 | Pending | Live dashboard |

## Detection pipeline

Process CCTV clips into structured events and feed the API:

```bash
# Install CV dependencies (optional — not needed for replay mode)
pip install -r requirements-pipeline.txt

# Replay sample events (no video required)
python -m pipeline.run --mode replay --output data/events/output.jsonl

# Process CCTV clips from data/clips/ (requires dataset mp4 files)
python -m pipeline.run --mode video --clips-dir data/clips --layout data/store_layout.json

# Pipeline + ingest into running API
python -m pipeline.run --mode replay --api-url http://localhost:8000
```

Place challenge clips in `data/clips/` using filenames like `STORE_BLR_002_CAM_ENTRY_01.mp4`.
Output events are written to `data/events/output.jsonl`.

## Project structure

```
store-intelligence/
├── app/           # FastAPI application
├── pipeline/      # CCTV detection + event emission
├── tests/         # Pytest suite
├── data/          # SQLite DB, POS, layout, clips (runtime)
├── docker-compose.yml
└── Dockerfile
```

## Dashboard Quickstart

Stream sample events into the running API and open the live dashboard.

PowerShell (Windows):

```powershell
# set PYTHONPATH for package imports (current session)
$env:PYTHONPATH='.'

# run the dashboard streamer (uses tests/fixtures/sample_events.jsonl by default)
python dashboard/run.py

# or use the provided helper
.\.scripts\run_dashboard.ps1
```

POSIX / WSL / macOS:

```bash
export PYTHONPATH="${PYTHONPATH:-.}"
./.scripts/run_dashboard.sh
```

Then open the dashboard URL printed by the streamer, for example:

http://127.0.0.1:8000/dashboard?store_id=STORE_BLR_002&date=2026-03-03

Notes:
- The wrappers set `PYTHONPATH` so `python dashboard/run.py` can import the `dashboard` package when run from the repo root.
- Use `docker compose up --build` to run the API in a container; the helper works inside the container too if the workspace is copied into `/app`.
