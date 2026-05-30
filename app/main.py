import logging
import time
import uuid
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import dispose_db, init_db
from app.routes.anomalies import router as anomalies_router
from app.routes.funnel import router as funnel_router
from app.routes.health import router as health_router
from app.routes.heatmap import router as heatmap_router
from app.routes.ingest import router as ingest_router
from app.routes.metrics import router as metrics_router
from app.routes.dashboard import router as dashboard_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(message)s",
    )
    await init_db()
    logger.info("store_intelligence_api_started version=%s", settings.app_version)
    yield
    await dispose_db()


app = FastAPI(
    title="Store Intelligence API",
    version=settings.app_version,
    lifespan=lifespan,
)

app.include_router(ingest_router)
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(funnel_router)
app.include_router(heatmap_router)
app.include_router(anomalies_router)
app.include_router(dashboard_router)

# Serve the dashboard static UI at /dashboard (index.html will be served)
repo_root = Path(__file__).resolve().parents[1]
dashboard_static = repo_root / "dashboard" / "static"
if dashboard_static.exists():
    # Mount dashboard assets under an internal static prefix so API routes
    # (for example `/dashboard/stream`) are not shadowed by the static file handler.
    app.mount(
        "/_dashboard_static",
        StaticFiles(directory=str(dashboard_static), html=True),
        name="dashboard_static",
    )

    # Serve the dashboard index at /dashboard by returning the static index.html
    from fastapi.responses import FileResponse

    @app.get("/dashboard")
    async def dashboard_index() -> FileResponse:
        return FileResponse(dashboard_static / "index.html")


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
    request.state.trace_id = trace_id
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    log_data = {
        "trace_id": trace_id,
        "store_id": getattr(request.state, "store_id", None),
        "endpoint": request.url.path,
        "latency_ms": latency_ms,
        "status_code": response.status_code,
    }
    event_count = getattr(request.state, "event_count", None)
    if event_count is not None:
        log_data["event_count"] = event_count
    # Emit structured JSON message prefixed with 'request ' for backward compatibility
    logger.info("request %s", json.dumps(log_data, default=str))
    response.headers["X-Trace-Id"] = trace_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled_error trace_id=%s", getattr(request.state, "trace_id", "-"))
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred.",
            "trace_id": getattr(request.state, "trace_id", None),
        },
    )
