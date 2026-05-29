import json
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal, engine, init_db
from app.db import Base
from app.main import app


FIXTURES = Path(__file__).parent / "fixtures"


def _valid_event(**overrides) -> dict:
    base = {
        "event_id": str(uuid4()),
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_c8a2f1",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:22:10Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.91,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
    }
    base.update(overrides)
    return base


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
async def reset_db():
    import app.tables  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def db_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


@pytest.fixture
def sample_events_from_file() -> list[dict]:
    path = FIXTURES / "sample_events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]
