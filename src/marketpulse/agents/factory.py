from __future__ import annotations

import asyncio
import json
import re
from typing import Protocol, TypeVar

import httpx
from agents import (
    Agent,
    ModelSettings,
    OpenAIChatCompletionsModel,
    Runner,
    set_tracing_disabled,
)
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from marketpulse.config import Settings
from marketpulse.errors import ConfigurationError, MarketPulseError, NoUsableEvidenceError
from marketpulse.investigation.harness.model_retry import retryable_model_error
from marketpulse.investigation.recording.diagnostics import provider_diagnostics

ModelT = TypeVar("ModelT", bound=BaseModel)


class AgentRunner(Protocol):
    async def run_json(
        self,
        *,
        name: str,
        instructions: str,
        prompt: str,
        schema: type[ModelT],
    ) -> ModelT: ...


def configure_deepseek(settings: Settings) -> AsyncOpenAI:
    """Create a run-scoped client; concurrent runs never replace each other's client."""
    if settings.deepseek_api_key is None:
        raise ConfigurationError("缺少 DEEPSEEK_API_KEY。")
    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key.get_secret_value(),
        base_url=settings.deepseek_base_url,
        timeout=httpx.Timeout(
            settings.model_read_timeout_seconds,
            connect=settings.model_connect_timeout_seconds,
            write=30.0,
            pool=15.0,
        ),
        max_retries=0,
    )
    set_tracing_disabled(True)
    return client


def _extract_json(text: str) -> str:
    cleaned = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            candidate = cleaned[start : end + 1]
            json.loads(candidate)
            return candidate
        raise


class DeepSeekAgentRunner:
    """Agents SDK wrapper with local Pydantic validation and one repair attempt."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = configure_deepseek(settings)

    async def aclose(self) -> None:
        await self.client.close()

    async def _run_readonly(self, agent: Agent, prompt: str):
        # Legacy CLI inference also has no tools/external writes. Retrying an
        # ambiguous request can duplicate provider billing, not a business action.
        retries = self.settings.model_retry_attempts if self.settings.model_auto_retry else 0
        for attempt in range(retries + 1):
            try:
                async with asyncio.timeout(
                    min(
                        self.settings.model_read_timeout_seconds,
                        self.settings.total_timeout_seconds,
                    )
                ):
                    return await Runner.run(agent, prompt, max_turns=2)
            except Exception as error:
                status = provider_diagnostics(error).get("http_status")
                if status == 402:
                    raise ConfigurationError("模型服务余额不足，请充值后重试。") from error
                if not retryable_model_error(error):
                    raise NoUsableEvidenceError(
                        f"模型服务确定性失败（HTTP {status or 'unknown'}），未自动重试。"
                    ) from error
                if attempt == retries:
                    raise NoUsableEvidenceError(
                        "网络不稳定，模型重试已耗尽；请检查网络/代理后重试。"
                    ) from error
                await asyncio.sleep(self.settings.model_retry_backoff_seconds * 2**attempt)
        raise AssertionError("unreachable readonly retry loop")

    async def run_json(
        self,
        *,
        name: str,
        instructions: str,
        prompt: str,
        schema: type[ModelT],
    ) -> ModelT:
        schema_hint = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        attempt_prompt = f"{prompt}\n\nReturn one JSON object matching this schema:\n{schema_hint}"
        last_error: Exception | None = None
        for attempt in range(2):
            critical = (
                "report" in name.casefold()
                or "verif" in name.casefold()
                or "analy" in name.casefold()
            )
            critical = critical and not self.settings.model_force_single
            chosen = self.settings.reasoning_model if critical else self.settings.model
            thinking = critical or self.settings.model_thinking_enabled
            agent = Agent(
                name=name,
                instructions=instructions,
                model=OpenAIChatCompletionsModel(chosen, self.client),
                model_settings=ModelSettings(
                    temperature=None if thinking else 0.0,
                    extra_body={
                        "thinking": {"type": "enabled" if thinking else "disabled"},
                        **(
                            {"reasoning_effort": self.settings.reasoning_effort} if thinking else {}
                        ),
                    },
                ),
            )
            if attempt:
                attempt_prompt += (
                    "\n\nYour previous output failed validation. Return corrected JSON only. "
                    f"Validation error category: {type(last_error).__name__}"
                )
            try:
                result = await self._run_readonly(agent, attempt_prompt)
                return schema.model_validate_json(_extract_json(str(result.final_output)))
            except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
                last_error = exc
            except MarketPulseError:
                raise
        raise NoUsableEvidenceError(f"{name} 未完成有效模型输出（{type(last_error).__name__}）。")
