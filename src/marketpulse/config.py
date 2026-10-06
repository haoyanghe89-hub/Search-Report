from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from marketpulse.errors import ConfigurationError


class Settings(BaseModel):
    """Runtime configuration loaded only at the composition root."""

    deepseek_api_key: SecretStr | None = None
    investigation_depth: str = Field(default="standard", pattern="^(quick|standard|deep)$")
    deepseek_base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    model_thinking_enabled: bool = False
    reasoning_model: str = "deepseek-v4-pro"
    model_force_single: bool = False
    reasoning_effort: str = Field(default="high", pattern="^(low|high|max)$")
    reasoning_output_tokens: int = Field(default=16000, ge=4000, le=64000)
    model_auto_retry: bool = True
    model_retry_attempts: int = Field(default=3, ge=0, le=4)
    model_retry_backoff_seconds: float = Field(default=1, ge=0, le=10)
    model_connect_timeout_seconds: float = Field(default=15, gt=0, le=60)
    model_read_timeout_seconds: float = Field(default=120, gt=0, le=600)
    total_timeout_seconds: float = Field(default=3600, gt=0, le=7200)
    max_search_queries: int = Field(default=240, ge=1, le=1000)
    max_initial_queries: int = Field(default=8, ge=1, le=12)
    max_pages: int = Field(default=600, ge=1, le=2000)
    page_timeout_seconds: float = Field(default=15, gt=0, le=60)
    max_page_bytes: int = Field(default=2 * 1024 * 1024, ge=1024)
    research_workers: int = Field(default=4, ge=1, le=4)
    max_search_concurrency: int = Field(default=4, ge=1, le=16)
    max_model_calls: int = Field(default=480, ge=1, le=2000)
    max_tokens: int = Field(default=2000000, ge=1000, le=10000000)
    analysis_max_sources: int = Field(default=8, ge=1, le=100)
    analysis_max_excerpts: int = Field(default=16, ge=1, le=200)
    analysis_max_chars: int = Field(default=24000, ge=1000, le=100000)
    model_context_items: int = Field(default=16, ge=1, le=100)
    model_metadata_chars: int = Field(default=500, ge=100, le=2000)
    verify_token_reserve_fraction: float = Field(default=0.25, ge=0, le=0.8)
    report_token_reserve_fraction: float = Field(default=0.02, ge=0, le=0.2)
    verify_call_reserve_fraction: float = Field(default=0.15, ge=0, le=0.8)
    report_call_reserve_fraction: float = Field(default=0.01, ge=0, le=0.2)
    max_queries_per_researcher: int = Field(default=3, ge=1, le=10)
    max_fetch_concurrency: int = Field(default=8, ge=1, le=32)
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
    max_research_rounds: int = Field(default=6, ge=1, le=20)
    auto_resume_enabled: bool = True
    recovery_scan_seconds: float = Field(default=15, ge=0.1, le=300)
    auto_resume_max_attempts: int = Field(default=3, ge=0, le=20)
    auto_resume_backoff_seconds: float = Field(default=15, ge=0, le=3600)
    stall_heartbeat_seconds: float = Field(default=90, ge=10, le=3600)
    stall_step_seconds: float = Field(default=900, ge=30, le=14400)
    reviewer_id: str | None = None
    reviewer_display_name: str | None = None
    reviewer_password_hash: SecretStr | None = None
    review_rate_limit_fingerprint_secret: SecretStr | None = None
    review_session_ttl_hours: float = Field(default=8, gt=0, le=168)
    review_rate_limit_max_failures: int = Field(default=5, ge=1, le=20)
    review_rate_limit_window_minutes: int = Field(default=15, ge=1, le=240)
    review_allowed_origins: tuple[str, ...] = (
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    review_allow_insecure_loopback: bool = True

    @field_validator("deepseek_base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value.startswith("https://"):
            raise ValueError("DeepSeek base URL must use HTTPS")
        return value

    @model_validator(mode="after")
    def validate_stage_reserves(self) -> Settings:
        if self.verify_token_reserve_fraction + self.report_token_reserve_fraction >= 1:
            raise ValueError("token reserve fractions must leave collection headroom")
        if self.verify_call_reserve_fraction + self.report_call_reserve_fraction >= 1:
            raise ValueError("call reserve fractions must leave collection headroom")
        return self

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
            model=values.get("MARKETPULSE_MODEL") or "deepseek-flash",
            reasoning_model=values.get("MARKETPULSE_REASONING_MODEL") or "deepseek-v4-pro",
            model_force_single=(values.get("MARKETPULSE_FORCE_SINGLE_MODEL") or "false").lower()
            in {"1", "true", "yes"},
            reasoning_effort=values.get("MARKETPULSE_REASONING_EFFORT") or "high",
            reasoning_output_tokens=int(
                values.get("MARKETPULSE_REASONING_OUTPUT_TOKENS") or "16000"
            ),
            model_auto_retry=(values.get("MARKETPULSE_MODEL_AUTO_RETRY") or "true").lower()
            in {"1", "true", "yes"},
            model_retry_attempts=int(values.get("MARKETPULSE_MODEL_RETRY_ATTEMPTS") or "3"),
            model_retry_backoff_seconds=float(
                values.get("MARKETPULSE_MODEL_RETRY_BACKOFF_SECONDS") or "1"
            ),
            model_connect_timeout_seconds=float(
                values.get("MARKETPULSE_MODEL_CONNECT_TIMEOUT") or "15"
            ),
            model_read_timeout_seconds=float(values.get("MARKETPULSE_MODEL_READ_TIMEOUT") or "120"),
            model_thinking_enabled=(values.get("MARKETPULSE_THINKING_ENABLED") or "false").lower()
            in {"1", "true", "yes"},
            total_timeout_seconds=float(values.get("MARKETPULSE_TOTAL_TIMEOUT_SECONDS") or "3600"),
            max_search_queries=int(values.get("MARKETPULSE_MAX_SEARCH_QUERIES") or "240"),
            max_pages=int(values.get("MARKETPULSE_MAX_PAGES") or "600"),
            research_workers=int(values.get("MARKETPULSE_RESEARCH_WORKERS") or "4"),
            max_search_concurrency=int(values.get("MARKETPULSE_SEARCH_CONCURRENCY") or "4"),
            max_fetch_concurrency=int(values.get("MARKETPULSE_FETCH_CONCURRENCY") or "8"),
            max_model_calls=int(values.get("MARKETPULSE_MAX_MODEL_CALLS") or "480"),
            max_tokens=int(values.get("MARKETPULSE_MAX_TOKENS") or "2000000"),
            analysis_max_sources=int(values.get("MARKETPULSE_ANALYSIS_MAX_SOURCES") or "8"),
            analysis_max_excerpts=int(values.get("MARKETPULSE_ANALYSIS_MAX_EXCERPTS") or "16"),
            analysis_max_chars=int(values.get("MARKETPULSE_ANALYSIS_MAX_CHARS") or "24000"),
            model_context_items=int(values.get("MARKETPULSE_MODEL_CONTEXT_ITEMS") or "16"),
            model_metadata_chars=int(values.get("MARKETPULSE_MODEL_METADATA_CHARS") or "500"),
            verify_token_reserve_fraction=float(
                values.get("MARKETPULSE_VERIFY_TOKEN_RESERVE") or "0.25"
            ),
            report_token_reserve_fraction=float(
                values.get("MARKETPULSE_REPORT_TOKEN_RESERVE") or "0.02"
            ),
            verify_call_reserve_fraction=float(
                values.get("MARKETPULSE_VERIFY_CALL_RESERVE") or "0.15"
            ),
            report_call_reserve_fraction=float(
                values.get("MARKETPULSE_REPORT_CALL_RESERVE") or "0.01"
            ),
            max_queries_per_researcher=int(values.get("MARKETPULSE_QUERIES_PER_RESEARCHER") or "3"),
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
            max_research_rounds=int(values.get("MARKETPULSE_MAX_RESEARCH_ROUNDS") or "6"),
            auto_resume_enabled=(values.get("INVESTIGATION_AUTO_RESUME") or "true").lower()
            in {"1", "true", "yes"},
            recovery_scan_seconds=float(values.get("INVESTIGATION_RECOVERY_SCAN_SECONDS") or "15"),
            auto_resume_max_attempts=int(
                values.get("INVESTIGATION_AUTO_RESUME_MAX_ATTEMPTS") or "3"
            ),
            auto_resume_backoff_seconds=float(
                values.get("INVESTIGATION_AUTO_RESUME_BACKOFF_SECONDS") or "15"
            ),
            stall_heartbeat_seconds=float(
                values.get("INVESTIGATION_STALL_HEARTBEAT_SECONDS") or "90"
            ),
            stall_step_seconds=float(values.get("INVESTIGATION_STALL_STEP_SECONDS") or "900"),
            reviewer_id=values.get("REVIEWER_ID") or None,
            reviewer_display_name=values.get("REVIEWER_DISPLAY_NAME") or "本地审核员",
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
            )
            or (
                "http://localhost:8000",
                "http://127.0.0.1:8000",
                "http://localhost:8080",
                "http://127.0.0.1:8080",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ),
            review_allow_insecure_loopback=(
                (values.get("REVIEW_ALLOW_INSECURE_LOOPBACK") or "true").lower()
                in {"1", "true", "yes"}
            ),
        )
