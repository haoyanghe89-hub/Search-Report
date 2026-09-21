from __future__ import annotations

import asyncio
import json
import re
from typing import Protocol, TypeVar

from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    set_tracing_disabled,
)
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from marketpulse.config import Settings
from marketpulse.errors import ConfigurationError, MarketPulseError, NoUsableEvidenceError

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
        timeout=60.0,
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
            agent = Agent(
                name=name,
                instructions=instructions,
                model=OpenAIChatCompletionsModel(self.settings.model, self.client),
            )
            if attempt:
                attempt_prompt += (
                    "\n\nYour previous output failed validation. Return corrected JSON only. "
                    f"Validation error category: {type(last_error).__name__}"
                )
            try:
                async with asyncio.timeout(min(90.0, self.settings.total_timeout_seconds)):
                    result = await Runner.run(agent, attempt_prompt, max_turns=2)
                return schema.model_validate_json(_extract_json(str(result.final_output)))
            except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
                last_error = exc
            except MarketPulseError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    continue
        raise NoUsableEvidenceError(f"{name} 未完成有效模型输出（{type(last_error).__name__}）。")
