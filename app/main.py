import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import dispose_db, init_db
from app.routes.anomalies import router as anomalies_router
from app.routes.funnel import router as funnel_router
from app.routes.health import router as health_router
from app.routes.heatmap import router as heatmap_router
from app.routes.ingest import router as ingest_router
from app.routes.metrics import router as metrics_router

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


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
    request.state.trace_id = trace_id
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    log_fields = (
        f"trace_id={trace_id} "
        f"store_id={getattr(request.state, 'store_id', '-')} "
        f"endpoint={request.url.path} "
        f"latency_ms={latency_ms} "
        f"status_code={response.status_code}"
    )
    event_count = getattr(request.state, "event_count", None)
    if event_count is not None:
        log_fields += f" event_count={event_count}"
    logger.info("request %s", log_fields)
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
