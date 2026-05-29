# Store Intelligence System — Architecture

## Overview

This system converts raw retail CCTV footage into live store analytics. It has three layers:

1. **Detection pipeline** (`pipeline/`) — YOLOv8 person detection + tracking, zone/entry-line geometry from `store_layout.json`, behavioural event emission as JSONL.
2. **Intelligence API** (`app/`) — FastAPI service that ingests events, computes real-time metrics, and exposes query endpoints.
3. **Live dashboard** (`dashboard/`) — Web UI connected to the API via Server-Sent Events; a streamer replays events on a simulated timeline to demonstrate end-to-end flow.

The north-star metric is **offline conversion rate**: visitors who purchased ÷ unique visitors. Detection accuracy feeds the numerator/denominator; the API makes the metric actionable through funnel, heatmap, and anomaly endpoints.

## Data flow

```
CCTV clips (.mp4)
    → YOLOv8 detect + track (pipeline/detect.py)
    → Zone / entry-line logic (pipeline/processor.py)
    → Structured events (JSONL)
    → POST /events/ingest
    → SQLite (events + store_feed_state)
    → Metrics / funnel / heatmap / anomalies (computed on read)
    → Dashboard SSE push (on ingest)
```

Events are immutable facts keyed by `event_id`. Analytics are derived at query time from stored events plus `pos_transactions.csv` for purchase correlation (5-minute billing-window rule).

## API design

- **Ingestion**: Per-event validation inside batches (partial success). Idempotent inserts via `ON CONFLICT DO NOTHING` on `event_id`.
- **Sessions**: Visitor sessions split on `ENTRY`/`REENTRY` → `EXIT`. Funnel and heatmap use sessions; metrics dedupe visitors at the day level.
- **Storage**: SQLite + SQLAlchemy async — sufficient for hackathon scale, zero external dependencies in Docker.
- **Observability**: Structured request logs (`trace_id`, `store_id`, `latency_ms`, `event_count`). `/health` reports per-store feed lag and `STALE_FEED` when last event > 10 minutes old.
- **Degradation**: Database failures return HTTP 503 with structured JSON — no stack traces in responses.

## Detection pipeline design

- **Model**: YOLOv8n — fast, good person-class performance on CPU/GPU, native tracking via Ultralytics ByteTrack integration.
- **Zones**: Normalised polygon hit-testing (ray casting) on bounding-box centroids — no VLM required for zone labels because `store_layout.json` defines geometry.
- **Re-entry**: Lightweight signature (position buckets + track seed) stored on exit; matched within 30-minute window → `REENTRY` instead of duplicate `ENTRY`.
- **Staff**: Hue heuristic on upper-body crop (green/teal uniform range). Imperfect but explainable; staff events excluded from customer metrics.
- **Replay mode**: Processes `sample_events.jsonl` without video — enables CI and API integration without the dataset.

## Dashboard

Ingest publishes metric snapshots to an in-memory pub/sub hub. Browser opens `/dashboard` and subscribes to `/dashboard/stream` (SSE). `dashboard/run.py` ingests events one-by-one on a compressed timeline (default 120×) so metrics visibly tick up during demo.

## Deployment

```bash
docker compose up --build   # API on :8000
```

Pipeline and dashboard run on the host (or a second container) because CV dependencies are heavy and clips are not in the repo.

## AI-Assisted Decisions

### 1. Session-based funnel vs visitor-day aggregation

**AI suggested**: Count unique `visitor_id` per day at each funnel stage.

**Decision**: Use **sessions** (`ENTRY`/`REENTRY` → `EXIT` blocks) as the funnel unit.

**Why**: The brief explicitly requires session semantics and re-entry handling. A visitor who exits and re-enters should appear as two sessions in the funnel, not inflate entry count incorrectly. I agreed with AI on excluding staff but overrode the visitor-level shortcut.

### 2. SQLite vs PostgreSQL

**AI suggested**: PostgreSQL for production parity.

**Decision**: **SQLite** with async SQLAlchemy.

**Why**: Acceptance gate requires `docker compose up` with no manual DB setup. SQLite satisfies idempotent ingest, session queries, and health feed state with one volume mount. I agreed PostgreSQL is the first scaling step at ~40 live stores with concurrent writes.

### 3. VLM for zone classification

**AI suggested**: GPT-4V / Claude Vision to label which zone a person is in from raw frames.

**Decision**: **Rule-based polygons** from `store_layout.json`.

**Why**: Challenge provides zone definitions per camera — a VLM adds latency, cost, and non-determinism without improving accuracy when layout metadata exists. I rejected VLM for zones but kept the door open for staff detection if hue heuristics fail on held-out clips.
