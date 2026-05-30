<!-- # create venv and install deps
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# run tests + coverage
python -m pytest --cov=app

# run API
uvicorn app.main:app --host 0.0.0.0 --port 8000

# or with docker
docker compose up --build
curl http://localhost:8000/health

# replay sample events into running API
python -m pipeline.run --mode replay --api-url http://localhost:8000 -->


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
docker compose up --build
```

Check health:

```powershell
curl http://localhost:8000/health
```

5. Replay sample events into the API (no video required)

```powershell
# optional: install CV pipeline deps
python -m pip install -r requirements-pipeline.txt

# replay mode (writes events to data/events/output.jsonl)
python -m pipeline.run --mode replay --output data/events/output.jsonl

# replay + ingest into running API
python -m pipeline.run --mode replay --api-url http://localhost:8000
```

Notes:
- The `docker compose` path is required by the hackathon acceptance gate — ensure Docker is installed.
- Use the branch `ci/add-ci-audit` for CI that runs tests and audits. Push and open a PR to trigger Actions.

If you want, I can also add these commands to a `Makefile` or `scripts/` helpers. Which do you prefer?

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

I can also add a `Makefile` target (e.g. `make demo`) if you prefer one-line commands.