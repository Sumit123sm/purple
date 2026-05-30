# PROMPT: Add focused unit tests for internal orchestration modules to improve statement coverage
# and validate non-route code paths in app.funnel, app.health_service, and pipeline.run.
# CHANGES MADE: Used lightweight monkeypatch stubs to avoid heavy dependencies while
# verifying batching, error handling, and branch behavior.

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


class _DummySession:
    def __init__(self, zone=False, billing=False, purchase=False):
        self._zone = zone
        self._billing = billing
        self._purchase = purchase

    def has_zone_visit(self):
        return self._zone

    def has_billing_queue(self):
        return self._billing


@pytest.mark.asyncio
async def test_compute_store_funnel_internal_branching(monkeypatch):
    from app import funnel as mod

    async def fake_fetch_store_events(_db, _store_id):
        return [SimpleNamespace(is_staff=False), SimpleNamespace(is_staff=True)]

    monkeypatch.setattr(mod, "fetch_store_events", fake_fetch_store_events)
    monkeypatch.setattr(mod, "resolve_target_date", lambda _events, td: td or date(2026, 3, 3))
    monkeypatch.setattr(mod, "filter_customer_events_for_date", lambda events, _d: events)
    monkeypatch.setattr(
        mod,
        "build_sessions",
        lambda _events: [
            _DummySession(zone=True, billing=True, purchase=True),
            _DummySession(zone=True, billing=False, purchase=False),
            _DummySession(zone=False, billing=False, purchase=False),
        ],
    )
    monkeypatch.setattr(mod, "session_has_purchase", lambda session, _sid, _d: session._purchase)

    response = await mod.compute_store_funnel(object(), "STORE_BLR_002", date(2026, 3, 3))
    stages = {stage.stage: stage for stage in response.stages}

    assert response.total_sessions == 3
    assert stages["entry"].count == 3
    assert stages["zone_visit"].count == 2
    assert stages["zone_visit"].drop_off_pct == 33.33
    assert stages["billing_queue"].count == 1
    assert stages["purchase"].count == 1


@pytest.mark.asyncio
async def test_compute_health_reports_stale_and_ok(monkeypatch):
    from app import health_service as mod

    now = datetime.now(timezone.utc)
    stale_ts = now - timedelta(minutes=25)
    fresh_ts = now - timedelta(minutes=2)

    class _Result:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return self

        def all(self):
            return self._items

    class _Session:
        async def execute(self, _query):
            return _Result(
                [
                    SimpleNamespace(store_id="STORE_OLD", last_event_at=stale_ts),
                    SimpleNamespace(store_id="STORE_NEW", last_event_at=fresh_ts),
                ]
            )

    monkeypatch.setattr(mod.settings, "health_stale_feed_minutes", 10)
    result = await mod.compute_health(_Session())

    assert result.status == "degraded"
    assert result.stores["STORE_OLD"]["feed_status"] == "STALE"
    assert result.stores["STORE_NEW"]["feed_status"] == "OK"
    assert any("STALE_FEED store=STORE_OLD" in warning for warning in result.warnings)


def test_ingest_to_api_handles_empty_events(capsys):
    from pipeline.run import ingest_to_api

    ingest_to_api([], "http://127.0.0.1:8000")
    out = capsys.readouterr().out
    assert "No events to ingest." in out


def test_ingest_to_api_batches_requests(monkeypatch):
    from pipeline import run as mod

    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"accepted": 2, "duplicates": 0, "rejected": 0}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json):
            calls.append((url, json))
            return _Response()

    monkeypatch.setattr(mod.httpx, "Client", _Client)

    events = [{"event_id": f"e-{i}"} for i in range(5)]
    mod.ingest_to_api(events, "http://localhost:8000/", batch_size=2)

    assert len(calls) == 3
    assert calls[0][0] == "http://localhost:8000/events/ingest"
    assert len(calls[0][1]["events"]) == 2
    assert len(calls[2][1]["events"]) == 1


def test_run_replay_mode_uses_explicit_source(monkeypatch, tmp_path):
    from pipeline import run as mod
    from pipeline.config import PipelineSettings

    source = tmp_path / "events.jsonl"
    source.write_text('{"event_id":"x"}\n', encoding="utf-8")
    output = tmp_path / "out.jsonl"

    settings = PipelineSettings(
        data_dir=tmp_path,
        clips_dir=tmp_path,
        layout_path=tmp_path / "layout.json",
        output_path=output,
        device="cpu",
    )

    captured = {}

    def fake_replay_events(src, out, store_id=None):
        captured["src"] = src
        captured["out"] = out
        captured["store_id"] = store_id
        return [{"event_id": "1"}]

    monkeypatch.setattr(mod, "replay_events", fake_replay_events)
    args = SimpleNamespace(replay_source=str(source), store_id="STORE_BLR_002")

    events = mod.run_replay_mode(settings, args)

    assert events == [{"event_id": "1"}]
    assert Path(captured["src"]) == source
    assert captured["out"] == output
    assert captured["store_id"] == "STORE_BLR_002"


def test_main_replay_success_and_failure_paths(monkeypatch, tmp_path):
    from pipeline import run as mod

    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(mod, "run_replay_mode", lambda settings, args: [{"event_id": "1"}])
    monkeypatch.setattr(mod, "ingest_to_api", lambda events, api_url: None)
    code_ok = mod.main(["--mode", "replay", "--api-url", "http://127.0.0.1:8000"])

    assert code_ok == 0

    def _boom(_settings, _args):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "run_replay_mode", _boom)
    code_fail = mod.main(["--mode", "replay"])
    assert code_fail == 1


def test_resolve_nonstandard_clips_with_clip_map(tmp_path):
    from pipeline import run as mod

    clips_dir = tmp_path / "CCTV Footage"
    clips_dir.mkdir(parents=True)
    clip_file = clips_dir / "CAM 1.mp4"
    clip_file.write_bytes(b"fake")

    clip_map = tmp_path / "clip_map.json"
    clip_map.write_text(
        '[{"filename":"CAM 1.mp4","store_id":"STORE_BLR_002","camera_id":"CAM_ENTRY_01"}]',
        encoding="utf-8",
    )

    layout = {
        "stores": [
            {
                "store_id": "STORE_BLR_002",
                "cameras": [{"camera_id": "CAM_ENTRY_01"}],
            }
        ]
    }

    resolved = mod._resolve_nonstandard_clips(
        clips_dir=clips_dir,
        layout=layout,
        clip_map_path=str(clip_map),
        default_store_id=None,
        default_camera_id=None,
    )

    assert len(resolved) == 1
    assert resolved[0][1] == "STORE_BLR_002"
    assert resolved[0][2] == "CAM_ENTRY_01"


def test_resolve_nonstandard_clips_with_default_store_cycles_cameras(tmp_path):
    from pipeline import run as mod

    clips_dir = tmp_path / "CCTV Footage"
    clips_dir.mkdir(parents=True)
    for name in ("CAM 1.mp4", "CAM 2.mp4", "CAM 3.mp4", "CAM 4.mp4"):
        (clips_dir / name).write_bytes(b"fake")

    layout = {
        "stores": [
            {
                "store_id": "STORE_BLR_002",
                "cameras": [
                    {"camera_id": "CAM_ENTRY_01"},
                    {"camera_id": "CAM_FLOOR_01"},
                    {"camera_id": "CAM_BILLING_01"},
                ],
            }
        ]
    }

    resolved = mod._resolve_nonstandard_clips(
        clips_dir=clips_dir,
        layout=layout,
        clip_map_path=None,
        default_store_id="STORE_BLR_002",
        default_camera_id=None,
    )

    assert len(resolved) == 4
    assert resolved[0][2] == "CAM_ENTRY_01"
    assert resolved[1][2] == "CAM_FLOOR_01"
    assert resolved[2][2] == "CAM_BILLING_01"
    assert resolved[3][2] == "CAM_ENTRY_01"
