from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+psycopg2://pipeline:pipeline@postgres:5432/pipeline"

    # Celery / Redis
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # LLM
    gemini_api_key: str = ""
    # Current GA model on the v1beta generateContent endpoint. gemini-1.5-flash
    # and gemini-2.0-flash have been retired; override via GEMINI_MODEL if needed
    # (e.g. "gemini-3.5-flash").
    gemini_model: str = "gemini-2.5-flash"
    llm_batch_size: int = 25
    llm_max_retries: int = 3

    # Storage
    upload_dir: str = "/data/uploads"

    # Anomaly detection
    anomaly_amount_multiplier: float = 3.0
    # Merchants that should only ever transact in INR.
    domestic_only_merchants: list[str] = [
        "Swiggy",
        "Ola",
        "IRCTC",
        "Zomato",
        "Paytm",
        "PhonePe",
        "BigBasket",
        "Flipkart",
        "Jio",
        "Airtel",
        "MakeMyTrip",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
