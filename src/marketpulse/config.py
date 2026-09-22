from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, field_validator

from marketpulse.errors import ConfigurationError


class Settings(BaseModel):
    """Runtime configuration loaded only at the composition root."""

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    total_timeout_seconds: float = Field(default=300, gt=0, le=600)
    max_search_queries: int = Field(default=12, ge=1, le=20)
    max_initial_queries: int = Field(default=8, ge=1, le=12)
    max_pages: int = Field(default=24, ge=1, le=50)
    page_timeout_seconds: float = Field(default=15, gt=0, le=60)
    max_page_bytes: int = Field(default=2 * 1024 * 1024, ge=1024)
    max_fetch_concurrency: int = Field(default=5, ge=1, le=10)
    max_retries: int = Field(default=2, ge=0, le=5)
    allow_proxy_dns: bool = False
    user_agent: str = "MarketPulseBot/0.1 (+local-cli)"
    search_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36 MarketPulse/0.1"
    )
    log_level: str = "INFO"
    database_url: SecretStr = SecretStr("sqlite:///data/blackboard.db")
    redis_url: SecretStr | None = None
    max_research_rounds: int = Field(default=2, ge=1, le=3)
    reviewer_id: str | None = None
    reviewer_display_name: str | None = None
    reviewer_password_hash: SecretStr | None = None
    review_rate_limit_fingerprint_secret: SecretStr | None = None
    review_session_ttl_hours: float = Field(default=8, gt=0, le=168)
    review_rate_limit_max_failures: int = Field(default=5, ge=1, le=20)
    review_rate_limit_window_minutes: int = Field(default=15, ge=1, le=240)
    review_allowed_origins: tuple[str, ...] = ()
    review_allow_insecure_loopback: bool = False

    @field_validator("deepseek_base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value.startswith("https://"):
            raise ValueError("DeepSeek base URL must use HTTPS")
        return value

    @classmethod
    def from_env(cls, *, require_api_key: bool = True, env_file: Path | None = None) -> Settings:
        # No implicit parent directory search and no mutation of process environment.
        path = env_file or Path(os.getenv("MARKETPULSE_ENV_FILE", ".env"))
        values = {**dotenv_values(path, interpolate=False), **os.environ}
        key = values.get("DEEPSEEK_API_KEY")
        if require_api_key and not key:
            raise ConfigurationError("缺少 DEEPSEEK_API_KEY。请在环境变量中配置后重试。")
        return cls(
            deepseek_api_key=SecretStr(key) if key else None,
            deepseek_base_url=values.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
            model=values.get("MARKETPULSE_MODEL") or "deepseek-chat",
            total_timeout_seconds=float(values.get("MARKETPULSE_TOTAL_TIMEOUT_SECONDS") or "300"),
            max_search_queries=int(values.get("MARKETPULSE_MAX_SEARCH_QUERIES") or "12"),
            max_pages=int(values.get("MARKETPULSE_MAX_PAGES") or "24"),
            page_timeout_seconds=float(values.get("MARKETPULSE_PAGE_TIMEOUT_SECONDS") or "15"),
            allow_proxy_dns=(values.get("MARKETPULSE_ALLOW_PROXY_DNS") or "false").lower()
            in {"1", "true", "yes"},
            log_level=(values.get("MARKETPULSE_LOG_LEVEL") or "INFO").upper(),
            database_url=SecretStr(
                values.get("MARKETPULSE_DATABASE_URL") or "sqlite:///data/blackboard.db"
            ),
            redis_url=SecretStr(values.get("MARKETPULSE_REDIS_URL") or "")
            if values.get("MARKETPULSE_REDIS_URL")
            else None,
            max_research_rounds=int(values.get("MARKETPULSE_MAX_RESEARCH_ROUNDS") or "2"),
            reviewer_id=values.get("REVIEWER_ID") or None,
            reviewer_display_name=values.get("REVIEWER_DISPLAY_NAME") or None,
            reviewer_password_hash=SecretStr(str(values["REVIEWER_PASSWORD_HASH"]))
            if values.get("REVIEWER_PASSWORD_HASH")
            else None,
            review_rate_limit_fingerprint_secret=SecretStr(
                str(values["REVIEW_RATE_LIMIT_FINGERPRINT_SECRET"])
            )
            if values.get("REVIEW_RATE_LIMIT_FINGERPRINT_SECRET")
            else None,
            review_session_ttl_hours=float(values.get("REVIEW_SESSION_TTL_HOURS") or "8"),
            review_rate_limit_max_failures=int(values.get("REVIEW_RATE_LIMIT_MAX_FAILURES") or "5"),
            review_rate_limit_window_minutes=int(
                values.get("REVIEW_RATE_LIMIT_WINDOW_MINUTES") or "15"
            ),
            review_allowed_origins=tuple(
                origin.strip()
                for origin in (values.get("REVIEW_ALLOWED_ORIGINS") or "").split(",")
                if origin.strip()
            ),
            review_allow_insecure_loopback=(
                values.get("REVIEW_ALLOW_INSECURE_LOOPBACK") or "false"
            ).lower()
            in {"1", "true", "yes"},
        )
