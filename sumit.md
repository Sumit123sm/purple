# Quick Setup & Run (Sumit)

These steps assume you're on Windows (PowerShell) and working from the repository root.

1. Create & activate a virtual environment

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
. \.venv\Scripts\Activate.ps1
```

2. Install runtime & test dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-pipeline.txt
```

3. Run tests

```powershell
python -m pytest -q
```

4. Run the API locally

```powershell
# start the app (development)
uvicorn app.main:app --host 0.0.0.0 --port 8000

# or via Docker (recommended for the acceptance gate):
docker compose up -d --build
```

Check health:

```powershell
curl http://localhost:8000/health
```

5. Replay sample events into the API (no video required)

```powershell
# replay mode (writes events to data/events/output.jsonl)
python -m pipeline.run --mode replay --output data/events/output.jsonl

# replay + ingest into running API
python -m pipeline.run --mode replay --api-url http://localhost:8000
```

6. Run local CCTV folder (optional, for video mode)

```powershell
python -m pipeline.run --mode video --clips-dir "CCTV Footage" --default-store-id STORE_BLR_002 --max-frames 300 --output data/events/output.jsonl
```

If clip names are non-standard, use a clip map:

```powershell
python -m pipeline.run --mode video --clips-dir "CCTV Footage" --clip-map data/clip_map.json --output data/events/output.jsonl
```

Notes:
- The `docker compose` path is required by the hackathon acceptance gate — ensure Docker is installed.
- Use the branch `ci/add-ci-audit` for CI that runs tests and audits. Push and open a PR to trigger Actions.

## Dashboard demo

To replay sample events into the API and view the live dashboard:

PowerShell:

```powershell
# set PYTHONPATH and run the streamer
.\.scripts\run_dashboard.ps1
```

Shell / WSL:

```bash
./.scripts/run_dashboard.sh
```

The streamer prints the dashboard URL (e.g. `http://127.0.0.1:8000/dashboard?store_id=STORE_BLR_002&date=2026-03-03`).
