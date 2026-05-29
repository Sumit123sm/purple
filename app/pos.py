import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.config import settings


@dataclass(frozen=True)
class PosTransaction:
    store_id: str
    transaction_id: str
    timestamp: datetime
    basket_value_inr: float


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_pos_transactions(path: str | Path | None = None) -> list[PosTransaction]:
    csv_path = Path(path or settings.pos_transactions_path)
    if not csv_path.exists():
        return []

    transactions: list[PosTransaction] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            transactions.append(
                PosTransaction(
                    store_id=row["store_id"].strip(),
                    transaction_id=row["transaction_id"].strip(),
                    timestamp=_parse_timestamp(row["timestamp"].strip()),
                    basket_value_inr=float(row["basket_value_inr"].strip()),
                )
            )
    return transactions


def get_store_transactions_for_date(
    store_id: str,
    target_date: date,
    path: str | Path | None = None,
) -> list[PosTransaction]:
    return [
        txn
        for txn in load_pos_transactions(path)
        if txn.store_id == store_id and txn.timestamp.date() == target_date
    ]


def conversion_window_start(txn_time: datetime) -> datetime:
    return txn_time - timedelta(minutes=settings.conversion_window_minutes)
