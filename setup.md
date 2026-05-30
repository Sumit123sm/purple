# Project Setup & Run Instructions

This file collects the exact commands and notes to run the project locally and reproduce the demo.

---

## Recommended (Docker)

1. Build and start services (clean):

```bash
docker compose build --no-cache
docker compose up -d
```

2. Verify health:

```bash
curl http://127.0.0.1:8000/health
```

3. Replay sample events into the running API:

```bash
python -m pipeline.run --mode replay --api-url http://127.0.0.1:8000
```

4. Open dashboard:

http://127.0.0.1:8000/dashboard?store_id=STORE_BLR_002&date=2026-03-03

---

## Without Docker (venv) — Windows PowerShell

1. Create & activate venv:

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
# For detection/video mode also run:
pip install -r requirements-pipeline.txt
```

3. Run tests:

```powershell
pytest -q
```

4. Start API:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

5. Replay sample events (in another shell):

```powershell
python -m pipeline.run --mode replay --api-url http://127.0.0.1:8000
```

6. Open dashboard:

http://127.0.0.1:8000/dashboard?store_id=STORE_BLR_002&date=2026-03-03

---

## Detection pipeline (video mode)

- Video mode requires OpenCV and Ultralytics. Install `requirements-pipeline.txt`.
- Model weights: ensure `yolov8n.pt` is available in the working directory or change `PipelineSettings.yolo_model`.
- CPU-only demo (works with or without ultralytics):

```bash
python -m pipeline.run --mode video --clips-dir data/clips --max-frames 200 --device cpu
```

- If `ultralytics` is NOT installed, the pipeline uses a deterministic synthetic fallback for demo purposes.

---

## Useful endpoints

- Health: `GET /health` → http://127.0.0.1:8000/health
- Metrics: `GET /stores/STORE_BLR_002/metrics?date=2026-03-03`
- Ingest (test): `POST /events/ingest` with `{"events": [...]}`
- Dashboard: `http://127.0.0.1:8000/dashboard?store_id=STORE_BLR_002&date=2026-03-03`

---

## Git / Submission notes

- `.gitignore` excludes large files: `data/clips/`, `*.pt`, `*.mp4`, `.env`, venvs, DB files.
- Small fixtures that are safe to commit: `data/store_layout.json`, `data/pos_transactions.csv`.
- Create PR via browser: https://github.com/Sumit123sm/purple/compare/main...submission/prepare?expand=1

Suggested PR Title:
```
Submission: Store Intelligence (final)
```
Suggested PR Body (paste into description):
```
Ready for review. Includes:
- Tests: 61 passing (pytest)
- Dashboard demo + streamer
- Pipeline CPU fallback & optional YOLOv8 path
- CI: tests + pip-audit + bandit
- Docs: README.md, sumit.md, DESIGN.md, CHOICES.md
```

---

## Troubleshooting

- Docker build fails due to missing model weights: run pipeline in `replay` mode instead (does not require weights).
- `gh` (GitHub CLI) missing: create PR in browser or install via `winget install --id GitHub.cli`.
- If `/events/ingest` returns 5xx, inspect logs:

```bash
docker compose logs --no-color --since 1m
# or if running locally with venv:
# check the terminal running uvicorn
```

---

## Quick checklist before submission

- [ ] `pytest` passes
- [ ] `docker compose up` starts API and `/health` returns OK
- [ ] `pipeline.run --mode replay` ingests events accepted by API
- [ ] Dashboard shows live metric updates
- [ ] `DESIGN.md` and `CHOICES.md` present and >250 words each
- [ ] Prompt blocks present at top of test files

---

File saved: `setup.md` at repo root. Keep this file with the repo for future demos.
