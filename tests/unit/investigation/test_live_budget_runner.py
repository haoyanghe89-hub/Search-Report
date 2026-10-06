"""The paid LIVE runner must not infer consent or add recovery budget."""

from pathlib import Path
from runpy import run_path

import pytest


@pytest.fixture
def request_builder():
    script = Path(__file__).resolve().parents[3] / "scripts/verify_live_token_budget.py"
    return run_path(str(script))["resume_request"]


def test_exact_unknown_consent_has_zero_budget_increase(request_builder):
    request = request_builder(
        {
            "can_resume": True,
            "state_version": 43,
            "unknown_calls": [{"intent_id": "first"}, {"intent_id": "second"}],
        },
        ["second", "first"],
    )
    assert request.expected_state_version == 43
    assert request.retry_unknown_intent_ids == ["second", "first"]
    assert not any(request.budget_increase.model_dump().values())


@pytest.mark.parametrize("consent", [[], ["other"], ["first", "extra"], ["first", "first"]])
def test_changed_or_duplicate_unknown_consent_is_rejected(request_builder, consent):
    with pytest.raises(ValueError, match="consent"):
        request_builder(
            {"can_resume": True, "state_version": 43, "unknown_calls": [{"intent_id": "first"}]},
            consent,
        )


def test_nonresumable_run_is_not_started(request_builder):
    with pytest.raises(ValueError, match="not resumable"):
        request_builder({"can_resume": False, "reason": "profile mismatch"}, [])
