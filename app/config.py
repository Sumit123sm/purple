from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./data/store_intelligence.db"
    log_level: str = "INFO"
    app_name: str = "store-intelligence-api"
    app_version: str = "0.1.0"
    pos_transactions_path: str = "./data/pos_transactions.csv"
    billing_zone_id: str = "BILLING"
    conversion_window_minutes: int = 5
    heatmap_confidence_session_threshold: int = 20
    anomaly_queue_spike_warn_depth: int = 3
    anomaly_queue_spike_critical_depth: int = 5
    anomaly_queue_spike_multiplier: float = 1.5
    anomaly_conversion_drop_threshold: float = 0.20
    anomaly_conversion_lookback_days: int = 7
    anomaly_dead_zone_minutes: int = 30
    health_stale_feed_minutes: int = 10


settings = Settings()
