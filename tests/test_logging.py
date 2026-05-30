# PROMPT: Write tests for structured request logging middleware to verify trace_id propagation,
# endpoint field correctness, latency presence, and JSON log payload parsing for observability.
# CHANGES MADE: Kept assertions focused on emitted JSON fields and retained caplog parsing.

import json
import logging

import pytest


@pytest.mark.asyncio
async def test_structured_request_logging(client, caplog):
    caplog.set_level(logging.INFO)
    with caplog.at_level(logging.INFO):
        response = await client.get("/health", headers={"X-Trace-Id": "test-trace-123"})

    assert response.status_code == 200

    # Find request logs
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO and "request " in r.getMessage()]
    assert messages, "no request log found"

    # Parse JSON payload from the first matching message
    raw = messages[0]
    # message format: 'request {..json..}'
    assert raw.startswith("request ")
    j = raw[len("request "):]
    data = json.loads(j)

    assert data["trace_id"] == "test-trace-123"
    assert data["endpoint"] == "/health"
    assert "latency_ms" in data
