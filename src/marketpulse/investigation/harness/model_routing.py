"""Explicit role selection before durable request identity and budget reservation."""

from typing import TypeVar

from pydantic import BaseModel

from marketpulse.config import Settings
from marketpulse.investigation.ports.external import ModelRequest

T = TypeVar("T", bound=BaseModel)


class ModelRoutingPolicy:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def route(self, request: ModelRequest[T]) -> ModelRequest[T]:
        role = request.prompt_version.rsplit(":", 1)[-1]
        critical = role.startswith(("verifier", "analyst", "source.quality", "source.independence"))
        critical = critical and not self.settings.model_force_single
        model = self.settings.reasoning_model if critical else self.settings.model
        if model in {"deepseek-chat", "deepseek-reasoner"}:
            raise ValueError("MODEL_ID_RETIRED: configure deepseek-flash or deepseek-v4-pro")
        thinking = True if critical else self.settings.model_thinking_enabled
        return request.model_copy(
            update={
                "model_hint": model,
                "thinking_enabled": thinking,
                "reasoning_effort": self.settings.reasoning_effort if thinking else None,
                "max_output_tokens": max(
                    request.max_output_tokens or 0, self.settings.reasoning_output_tokens
                )
                if thinking
                else request.max_output_tokens,
            }
        )
