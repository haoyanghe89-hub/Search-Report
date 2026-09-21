from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from marketpulse.investigation.ports.external import (
    ModelRequest,
    ModelUsage,
    StructuredModelResult,
)
from marketpulse.investigation.recording.errors import (
    InvalidProviderResponseError,
    ProviderCallError,
    RateLimitedError,
)

T = TypeVar("T", bound=BaseModel)


def _json_payload(content: str) -> str:
    value = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, re.DOTALL)
    if fenced:
        value = fenced.group(1).strip()
    return value


class OpenAICompatibleModelAdapter:
    """Generic structured-output adapter; prompts remain supplied by callers."""

    def __init__(self, client: Any, *, provider: str, default_model: str) -> None:
        self._client = client
        self._provider = provider
        self._default_model = default_model

    async def generate(self, request: ModelRequest[T]) -> StructuredModelResult[T]:
        model = request.model_hint or self._default_model
        schema = json.dumps(request.response_model.model_json_schema(), ensure_ascii=False)
        messages = [message.model_dump() for message in request.messages]
        messages.append(
            {
                "role": "system",
                "content": f"Return only one JSON object matching this schema: {schema}",
            }
        )
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "response_format": {"type": "json_object"},
        }
        if request.max_output_tokens is not None:
            kwargs["max_tokens"] = request.max_output_tokens
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as error:
            if getattr(error, "status_code", None) == 429:
                raise RateLimitedError("model provider rate limited the request") from error
            raise ProviderCallError("model provider request failed") from error
        try:
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty model content")
            output = request.response_model.model_validate_json(_json_payload(content))
        except (AttributeError, IndexError, TypeError, ValueError, ValidationError) as error:
            raise InvalidProviderResponseError("model response failed typed validation") from error
        usage = getattr(response, "usage", None)
        return StructuredModelResult[T](
            output=output,
            provider=self._provider,
            model=model,
            usage=ModelUsage(
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
            ),
            response_id=getattr(response, "id", None),
        )
