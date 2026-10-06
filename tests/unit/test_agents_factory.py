from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai import APIStatusError

from marketpulse.agents.factory import DeepSeekAgentRunner, _extract_json
from marketpulse.config import Settings
from marketpulse.errors import ConfigurationError, NoUsableEvidenceError


def test_extract_json_accepts_fenced_payload() -> None:
    assert _extract_json('```json\n{"answer": 1}\n```') == '{"answer": 1}'


def test_extract_json_discards_surrounding_prose() -> None:
    assert _extract_json('Here is the result: {"answer": 1} done') == '{"answer": 1}'


@pytest.mark.asyncio
async def test_legacy_readonly_transport_retries_are_bounded():
    runner = object.__new__(DeepSeekAgentRunner)
    runner.settings = Settings(model_retry_attempts=2, model_retry_backoff_seconds=0.01)
    success = SimpleNamespace(final_output='{"answer":1}')
    with patch("marketpulse.agents.factory.Runner.run", new=AsyncMock()) as run:
        run.side_effect = [TimeoutError(), ConnectionResetError(), success]
        assert await runner._run_readonly(SimpleNamespace(), "prompt") is success
        assert run.await_count == 3
        run.reset_mock()
        run.side_effect = TimeoutError()
        with pytest.raises(NoUsableEvidenceError, match="网络不稳定"):
            await runner._run_readonly(SimpleNamespace(), "prompt")
        assert run.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 402])
async def test_legacy_deterministic_failure_does_not_retry(status):
    runner = object.__new__(DeepSeekAgentRunner)
    runner.settings = Settings()
    error = APIStatusError(
        "redacted",
        response=httpx.Response(status, request=httpx.Request("POST", "https://api.test")),
        body=None,
    )
    with patch("marketpulse.agents.factory.Runner.run", new=AsyncMock(side_effect=error)) as run:
        with pytest.raises(
            ConfigurationError if status == 402 else NoUsableEvidenceError,
            match="余额不足" if status == 402 else "确定性失败",
        ):
            await runner._run_readonly(SimpleNamespace(), "prompt")
        assert run.await_count == 1
