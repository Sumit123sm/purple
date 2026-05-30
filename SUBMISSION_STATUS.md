# Submission Status (Current Snapshot)

Last updated: 2026-05-30

This file records what is currently implemented and verified in this repository for the Purplle Round 2 challenge.

## Acceptance Gate Snapshot

1. **Runs via Docker**: ✅ Verified (`docker compose up -d --build` starts API).
2. **Produces events**: ✅ README explains replay and video pipeline commands and output path (`data/events/output.jsonl`).
3. **Ingest works**: ✅ Verified replay ingest (`accepted=5`, no 5xx observed).
4. **Metrics responds**: ✅ Verified `GET /stores/STORE_BLR_002/metrics` returns valid JSON.
5. **Docs exist and non-trivial**: ✅ `docs/DESIGN.md` and `docs/CHOICES.md` present and detailed.

## Implemented Challenge Parts

- **Part A (Detection pipeline)**: Implemented (`pipeline/`), supports replay and video modes.
- **Part B (Intelligence API)**: Implemented endpoints for ingest, metrics, funnel, heatmap, anomalies, health.
- **Part C (Production readiness)**: Dockerized app, structured logging tests, idempotent ingest behavior, graceful degradation tests, coverage run previously observed above 70%.
- **Part D (AI engineering artifacts)**: Prompt headers present in tests, plus `DESIGN.md` and `CHOICES.md` include AI-assisted decision rationale.
- **Part E (Dashboard bonus)**: Dashboard route + streamer scripts available.

## Important Dataset / Video Policy

- Dataset and CCTV videos are **not** committed.
- `.gitignore` excludes `*.mp4`, `data/clips/`, and `CCTV Footage/`.

## Known Current Gap

- Running video mode on local `CCTV Footage/` currently processes clips successfully but emitted `0` events in recent smoke runs. This is a model/threshold quality issue for full Part A scoring, not an API or container startup blocker.

## Current Primary Run Commands

```bash
# API
docker compose up -d --build

# Replay into API
python -m pipeline.run --mode replay --api-url http://127.0.0.1:8000

# Video mode with local CCTV folder
python -m pipeline.run --mode video --clips-dir "CCTV Footage" --default-store-id STORE_BLR_002 --max-frames 300 --output data/events/output.jsonl
```
