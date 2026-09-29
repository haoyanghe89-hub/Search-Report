from __future__ import annotations

import pytest

from marketpulse.budget import RunBudget
from marketpulse.config import Settings
from marketpulse.errors import BudgetExceeded, ConfigurationError


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("MARKETPULSE_ALLOW_PROXY_DNS", raising=False)
    settings = Settings.from_env()
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.model == "deepseek-flash"
    assert settings.total_timeout_seconds == 1800
    assert settings.max_search_queries == 120
    assert settings.max_pages == 300
    assert settings.allow_proxy_dns is False


def test_review_has_no_builtin_credential() -> None:
    settings = Settings()
    assert settings.reviewer_id is None
    assert settings.reviewer_password_hash is None
    assert settings.review_rate_limit_fingerprint_secret is None


def test_settings_can_enable_proxy_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("MARKETPULSE_ALLOW_PROXY_DNS", "true")
    assert Settings.from_env().allow_proxy_dns is True


def test_settings_requires_deepseek_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_budget_query_limit(settings: Settings, ticking_clock: object) -> None:
    _, clock = ticking_clock  # type: ignore[misc]
    budget = RunBudget.start(settings, clock)  # type: ignore[arg-type]
    for _ in range(12):
        budget.reserve_search()
    with pytest.raises(BudgetExceeded, match="search_queries"):
        budget.reserve_search()


def test_budget_wall_time(settings: Settings, ticking_clock: object) -> None:
    value, clock = ticking_clock  # type: ignore[misc]
    budget = RunBudget.start(settings, clock)  # type: ignore[arg-type]
    value[0] += 300
    with pytest.raises(BudgetExceeded, match="wall_time"):
        budget.ensure_time_remaining()
