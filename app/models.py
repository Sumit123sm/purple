from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class EventType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


class EventMetadata(BaseModel):
    queue_depth: int | None = None
    sku_zone: str | None = None
    session_seq: int | None = None


class StoreEvent(BaseModel):
    event_id: UUID
    store_id: str = Field(..., min_length=1)
    camera_id: str = Field(..., min_length=1)
    visitor_id: str = Field(..., min_length=1)
    event_type: EventType
    timestamp: datetime
    zone_id: str | None = None
    dwell_ms: int = Field(default=0, ge=0)
    is_staff: bool = False
    confidence: float = Field(..., ge=0.0, le=1.0)
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        raise ValueError("timestamp must be ISO-8601")

    model_config = {"extra": "forbid"}


class IngestRequest(BaseModel):
    events: list[StoreEvent] = Field(..., max_length=500)


class IngestResult(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
    errors: list[dict[str, str]] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    version: str
    stores: dict[str, dict[str, Any]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class StoreMetricsResponse(BaseModel):
    store_id: str
    date: str
    unique_visitors: int
    converted_visitors: int
    conversion_rate: float
    avg_dwell_per_zone: dict[str, float]
    queue_depth: int
    abandonment_rate: float
    computed_at: datetime


class FunnelStage(BaseModel):
    stage: str
    count: int
    drop_off_pct: float


class FunnelResponse(BaseModel):
    store_id: str
    date: str
    total_sessions: int
    stages: list[FunnelStage]
    computed_at: datetime


class HeatmapZone(BaseModel):
    zone_id: str
    visit_frequency: int = Field(..., ge=0, le=100)
    avg_dwell: int = Field(..., ge=0, le=100)
    visit_count: int = Field(..., ge=0)
    avg_dwell_ms: float = Field(..., ge=0)


class HeatmapResponse(BaseModel):
    store_id: str
    date: str
    session_count: int
    data_confidence: str
    zones: list[HeatmapZone]
    computed_at: datetime


class AnomalyItem(BaseModel):
    anomaly_type: str
    severity: str
    message: str
    suggested_action: str
    detected_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnomaliesResponse(BaseModel):
    store_id: str
    date: str
    active_anomalies: list[AnomalyItem]
    computed_at: datetime
