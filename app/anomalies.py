import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.metrics import compute_store_metrics
from app.models import AnomaliesResponse, AnomalyItem
from app.sessions import (
    HEATMAP_ZONE_EVENTS,
    as_utc,
    fetch_store_events,
    filter_customer_events_for_date,
    resolve_target_date,
)

ANOMALY_QUEUE_SPIKE = "BILLING_QUEUE_SPIKE"
ANOMALY_CONVERSION_DROP = "CONVERSION_DROP"
ANOMALY_DEAD_ZONE = "DEAD_ZONE"


async def compute_store_anomalies(
    session: AsyncSession,
    store_id: str,
    target_date: date | None = None,
) -> AnomaliesResponse:
    events = await fetch_store_events(session, store_id)
    customer_events = [event for event in events if not event.is_staff]
    resolved_date = resolve_target_date(customer_events, target_date)
    day_events = filter_customer_events_for_date(customer_events, resolved_date)
    reference_time = _reference_time(day_events, resolved_date)

    anomalies: list[AnomalyItem] = []

    queue_anomaly = _detect_queue_spike(day_events, reference_time)
    if queue_anomaly:
        anomalies.append(queue_anomaly)

    conversion_anomaly = await _detect_conversion_drop(
        session, store_id, resolved_date, reference_time
    )
    if conversion_anomaly:
        anomalies.append(conversion_anomaly)

    anomalies.extend(_detect_dead_zones(day_events, reference_time))

    return AnomaliesResponse(
        store_id=store_id,
        date=resolved_date.isoformat(),
        active_anomalies=anomalies,
        computed_at=datetime.now(timezone.utc),
    )


def _reference_time(day_events, resolved_date: date) -> datetime:
    if day_events:
        return as_utc(day_events[-1].timestamp)
    return datetime.combine(resolved_date, datetime.max.time(), tzinfo=timezone.utc)


def _detect_queue_spike(day_events, reference_time: datetime) -> AnomalyItem | None:
    depths: list[int] = []
    latest_depth = 0
    latest_ts: datetime | None = None

    for event in day_events:
        if event.event_type != "BILLING_QUEUE_JOIN":
            continue
        metadata = json.loads(event.metadata_json)
        queue_depth = metadata.get("queue_depth")
        if queue_depth is None:
            continue
        depth = int(queue_depth)
        depths.append(depth)
        event_ts = as_utc(event.timestamp)
        if latest_ts is None or event_ts >= latest_ts:
            latest_ts = event_ts
            latest_depth = depth

    if latest_depth <= 0:
        return None

    avg_depth = sum(depths) / len(depths)
    spike_threshold = max(avg_depth * settings.anomaly_queue_spike_multiplier, 2.0)
    if latest_depth < spike_threshold:
        return None

    if latest_depth >= settings.anomaly_queue_spike_critical_depth:
        severity = "CRITICAL"
        action = "Open additional billing counter and deploy floor staff to queue management immediately."
    elif latest_depth >= settings.anomaly_queue_spike_warn_depth:
        severity = "WARN"
        action = "Notify store manager to monitor billing queue and prepare backup cashier."
    else:
        severity = "INFO"
        action = "Keep an eye on billing queue length during the next 15 minutes."

    return AnomalyItem(
        anomaly_type=ANOMALY_QUEUE_SPIKE,
        severity=severity,
        message=f"Billing queue depth spiked to {latest_depth} (day average {avg_depth:.1f}).",
        suggested_action=action,
        detected_at=reference_time,
        metadata={"queue_depth": latest_depth, "average_queue_depth": round(avg_depth, 2)},
    )


async def _detect_conversion_drop(
    session: AsyncSession,
    store_id: str,
    target_date: date,
    reference_time: datetime,
) -> AnomalyItem | None:
    today_metrics = await compute_store_metrics(session, store_id, target_date)
    if today_metrics.unique_visitors == 0:
        return None

    historical_rates: list[float] = []
    for offset in range(1, settings.anomaly_conversion_lookback_days + 1):
        historical_date = target_date - timedelta(days=offset)
        metrics = await compute_store_metrics(session, store_id, historical_date)
        if metrics.unique_visitors > 0:
            historical_rates.append(metrics.conversion_rate)

    if not historical_rates:
        return None

    baseline = sum(historical_rates) / len(historical_rates)
    today_rate = today_metrics.conversion_rate
    drop_pct = 0.0 if baseline == 0 else ((baseline - today_rate) / baseline) * 100

    if drop_pct < settings.anomaly_conversion_drop_threshold * 100:
        return None

    if drop_pct >= 50:
        severity = "CRITICAL"
        action = "Investigate billing bottlenecks, staffing gaps, and out-of-stock hero SKUs immediately."
    elif drop_pct >= 30:
        severity = "WARN"
        action = "Review today's in-store promotions and billing wait times with the shift lead."
    else:
        severity = "INFO"
        action = "Track conversion hourly and compare zone dwell patterns with prior week."

    return AnomalyItem(
        anomaly_type=ANOMALY_CONVERSION_DROP,
        severity=severity,
        message=(
            f"Conversion rate {today_rate:.2%} is below the "
            f"{len(historical_rates)}-day average {baseline:.2%} (drop {drop_pct:.1f}%)."
        ),
        suggested_action=action,
        detected_at=reference_time,
        metadata={
            "today_conversion_rate": today_rate,
            "baseline_conversion_rate": round(baseline, 4),
            "drop_pct": round(drop_pct, 2),
        },
    )


def _detect_dead_zones(day_events, reference_time: datetime) -> list[AnomalyItem]:
    if not day_events:
        return []

    cutoff = reference_time - timedelta(minutes=settings.anomaly_dead_zone_minutes)
    zone_events: dict[str, list[datetime]] = {}

    for event in day_events:
        if not event.zone_id:
            continue
        if event.event_type not in HEATMAP_ZONE_EVENTS:
            continue
        zone_events.setdefault(event.zone_id, []).append(as_utc(event.timestamp))

    anomalies: list[AnomalyItem] = []
    for zone_id, timestamps in sorted(zone_events.items()):
        had_activity_before_cutoff = any(ts < cutoff for ts in timestamps)
        recent_activity = any(cutoff <= ts <= reference_time for ts in timestamps)
        if not had_activity_before_cutoff or recent_activity:
            continue

        last_visit = max(timestamps)
        idle_minutes = int((reference_time - last_visit).total_seconds() // 60)

        if idle_minutes >= 60:
            severity = "CRITICAL"
            action = f"Check camera coverage and staffing for {zone_id}; zone may be blocked or mis-merchandised."
        elif idle_minutes >= 45:
            severity = "WARN"
            action = f"Send floor associate to {zone_id} to refresh display and engage walk-in traffic."
        else:
            severity = "INFO"
            action = f"Monitor {zone_id} footfall over the next 15 minutes before taking action."

        anomalies.append(
            AnomalyItem(
                anomaly_type=ANOMALY_DEAD_ZONE,
                severity=severity,
                message=f"Zone {zone_id} has had no customer visits for {idle_minutes} minutes.",
                suggested_action=action,
                detected_at=reference_time,
                metadata={"zone_id": zone_id, "idle_minutes": idle_minutes},
            )
        )

    return anomalies
