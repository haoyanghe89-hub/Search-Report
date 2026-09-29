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
    ModelOutputTruncatedError,
    ProviderCallError,
    RateLimitedError,
)

T = TypeVar("T", bound=BaseModel)


def _schema_fields(schema: Any) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    fields = set(schema.get("properties", {}))
    for value in schema.values():
        if isinstance(value, dict):
            fields.update(_schema_fields(value))
        elif isinstance(value, list):
            for item in value:
                fields.update(_schema_fields(item))
    return fields


def _json_payload(content: str) -> str:
    value = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, re.DOTALL)
    if fenced:
        value = fenced.group(1).strip()
    return value


class OpenAICompatibleModelAdapter:
    """Generic structured-output adapter; prompts remain supplied by callers."""

    def __init__(
        self,
        client: Any,
        *,
        provider: str,
        default_model: str,
        thinking_enabled: bool | None = None,
    ) -> None:
        self._client = client
        self._provider = provider
        self._default_model = default_model
        self._thinking_enabled = thinking_enabled

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
        if self._thinking_enabled is not None and model.startswith("deepseek-"):
            kwargs["extra_body"] = {
                "thinking": {"type": "enabled" if self._thinking_enabled else "disabled"}
            }
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as error:
            if getattr(error, "status_code", None) == 429:
                raise RateLimitedError("model provider rate limited the request") from error
            raise ProviderCallError("model provider request failed") from error
        try:
            if getattr(response.choices[0], "finish_reason", None) == "length":
                raise ModelOutputTruncatedError("model output token limit reached")
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty model content")
            output = request.response_model.model_validate_json(_json_payload(content))
        except ValidationError as error:
            # Only schema paths and error codes, never response text or rejected values.
            fields = _schema_fields(request.response_model.model_json_schema())
            issues = tuple(
                ".".join(
                    str(part) if isinstance(part, int) or part in fields else "<field>"
                    for part in item["loc"]
                )
                + ": "
                + item["type"]
                for item in error.errors(include_input=False, include_context=False)[:12]
            )
            raise InvalidProviderResponseError(
                "model response failed typed validation", validation_issues=issues
            ) from error
        except (AttributeError, IndexError, TypeError, ValueError) as error:
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
