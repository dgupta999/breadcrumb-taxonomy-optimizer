"""Runtime configuration, read from environment / .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    # Supabase Postgres connection string, e.g.
    # postgresql+psycopg://postgres:<pw>@db.<ref>.supabase.co:5432/postgres
    # Falls back to a local SQLite file so the tool runs without Supabase.
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{(BASE_DIR / 'data' / 'bto.db').as_posix()}")
    data_dir: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))

    # Optional shared secret. When set, every /api request must send
    # "Authorization: Bearer <API_TOKEN>".
    api_token: str | None = os.getenv("API_TOKEN") or None
    cors_origins: list[str] = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

    # Run the job worker inside the API process (handy for local dev).
    # In production run `python -m app.worker` as a separate process instead.
    embedded_worker: bool = _bool("EMBEDDED_WORKER", True)
    worker_poll_seconds: float = float(os.getenv("WORKER_POLL_SECONDS", "2"))

    # LLM fallback (only used for ambiguous decisions / missing translations).
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY") or None
    llm_enabled: bool = _bool("LLM_ENABLED", True)
    llm_model: str = os.getenv("LLM_MODEL", "claude-opus-5-5")
    llm_effort: str = os.getenv("LLM_EFFORT", "low")
    llm_max_calls_per_job: int = int(os.getenv("LLM_MAX_CALLS_PER_JOB", "500"))

    # Crawler defaults
    crawl_user_agent: str = os.getenv(
        "CRAWL_USER_AGENT",
        "BreadcrumbTaxonomyOptimizer/1.0 (+internal SEO research; respects robots.txt)",
    )
    crawl_delay_seconds: float = float(os.getenv("CRAWL_DELAY_SECONDS", "1.5"))
    crawl_timeout_seconds: float = float(os.getenv("CRAWL_TIMEOUT_SECONDS", "30"))
    crawl_max_retries: int = int(os.getenv("CRAWL_MAX_RETRIES", "2"))

    @property
    def llm_available(self) -> bool:
        return self.llm_enabled and bool(self.anthropic_api_key)


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / "uploads").mkdir(exist_ok=True)
(settings.data_dir / "exports").mkdir(exist_ok=True)
