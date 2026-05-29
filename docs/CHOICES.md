# Engineering Choices

This document explains three core decisions: detection model, event schema, and API architecture. Each section lists alternatives considered, what AI tools suggested, and what I chose with reasoning.

---

## 1. Detection model: YOLOv8n + Ultralytics tracking

### Options considered

| Option | Pros | Cons |
|--------|------|------|
| **YOLOv8n** (chosen) | Fast, built-in ByteTrack, easy clip batching, strong person class | Struggles with heavy occlusion in crowded billing |
| YOLOv9 / RT-DETR | Higher mAP on benchmarks | Heavier; marginal gain for fixed-camera retail |
| MediaPipe | Lightweight, no GPU | Weaker in crowded scenes; limited tracking story |
| VLM (GPT-4V) for all detection | Handles ambiguity | Too slow for 15fps×3 cameras×20min; not batch-friendly |

### What AI suggested

ChatGPT/Cursor recommended starting with **YOLOv8 + ByteTrack** as the default retail CV stack, with optional StrongSORT if re-ID errors appeared at the entry line.

### What I chose and why

**YOLOv8n** with Ultralytics `.track(persist=True, classes=[0])`.

Retail CCTV here is fixed-angle, person-only, 1080p/15fps. Nano variant keeps CPU inference viable during development. Tracking IDs come from ByteTrack inside Ultralytics — I did not add a separate Re-ID model initially; instead, `SessionManager` handles cross-visit re-entry with exit signatures.

**Trade-off accepted**: When a customer leaves and someone else enters within seconds from the same direction, track IDs may swap. Mitigation: entry-line events gate session starts; re-entry uses signature matching only after a prior `EXIT`.

**If I had more time**: Fine-tune YOLO on challenge frames; add OSNet re-ID for billing overlap with entry camera.

---

## 2. Event schema design

### Options considered

| Option | Pros | Cons |
|--------|------|------|
| **Behavioural event catalogue** (chosen) | Maps directly to funnel, metrics, anomalies | Requires thoughtful pipeline emission rules |
| Raw frame detections stream | Simple to emit | Useless for business APIs without heavy aggregation |
| Nested session documents | Fewer rows | Hard to idempotently ingest and partial-replay |

### What AI suggested

AI proposed a flat JSON schema with `event_id`, `visitor_id`, enum `event_type`, and a metadata bag for extensibility. It also suggested **not** dropping low-confidence events — flag them instead.

### What I chose and why

I adopted the **challenge schema verbatim** as Pydantic models (`app/models.py`) with `extra=forbid` to catch pipeline bugs early.

Key rationale:

- **`event_id` (UUID)**: Enables idempotent ingest — critical for replay and retry.
- **Separate `ENTRY` vs `REENTRY`**: Makes funnel/session logic explicit instead of inferring re-entry from timestamps alone.
- **`dwell_ms` on `ZONE_DWELL`**: Supports heatmap averages without reprocessing raw tracks.
- **`metadata.queue_depth`**: Required for billing queue anomalies and metrics; kept nullable for other types.
- **Loose ingest body** (`list[dict]`) with per-row validation: Enables partial batch success as required by the brief.

**Trade-off accepted**: More event types to emit correctly in the pipeline than a minimal entry/exit-only design. The API complexity stays low because events are facts, not aggregates.

---

## 3. API architecture: compute-on-read vs materialised views

### Options considered

| Option | Pros | Cons |
|--------|------|------|
| **Compute-on-read from events** (chosen) | Always fresh; simpler ingest path | Heavier reads at very large scale |
| Materialised metrics tables updated on ingest | Fast reads | Sync bugs; stale data risk; harder idempotent replay |
| Stream processor (Kafka/Flink) | True realtime at scale | Out of scope for solo hackathon + docker compose gate |

### What AI suggested

AI recommended a **streaming aggregation** pattern (Redis counters per store/zone). For MVP it also suggested SQLite + compute-on-read as acceptable if documented.

### What I chose and why

**FastAPI + SQLite + compute-on-read** in `metrics.py`, `funnel.py`, `heatmap.py`, `anomalies.py`.

Ingest only writes events and updates `store_feed_state.last_event_at`. Every analytics endpoint queries events for the requested store/date and derives answers in Python.

Why this fits the brief:

- **Real-time** means “reflects all ingested events so far today,” not cached yesterday — compute-on-read guarantees that after ingest.
- **Replay/demo friendly**: Re-ingesting a clip immediately changes metrics without invalidating caches.
- **Testability**: 67 pytest tests validate edge cases (empty store, staff exclusion, re-entry sessions, zero purchases).

**SSE dashboard hook**: On successful ingest, `notify_store_metrics()` recomputes and pushes to subscribers — gives live UX without a separate stream processor.

**First thing that breaks at 40 stores** (honest answer): SQLite write contention on concurrent ingests and full-table scans per metrics call. Migration path: PostgreSQL + indexed `(store_id, timestamp)` + optional daily rollup job — ingest path unchanged.

---

## Staff detection note (VLM vs heuristic)

I tried a **VLM prompt** conceptually for staff (“Is this person wearing a staff uniform?”) but implemented **HSV hue on upper-body crop** instead for speed and repeatability. On synthetic tests it flags green/teal ranges. Evaluating held-out clips may require adjusting hue bounds or adding a small classifier — the pipeline keeps `is_staff` as a first-class field so API exclusion works regardless of detection quality.
