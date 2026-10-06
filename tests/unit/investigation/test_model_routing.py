import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from marketpulse.config import Settings
from marketpulse.investigation.adapters.model import OpenAICompatibleModelAdapter
from marketpulse.investigation.harness.model_routing import ModelRoutingPolicy
from marketpulse.investigation.ports.external import ModelMessage, ModelRequest


class Answer(BaseModel):
    answer: str


def request(role):
    return ModelRequest(
        messages=(ModelMessage(role="user", content="test"),),
        response_model=Answer,
        response_schema_version="1",
        prompt_version="v1:" + role,
        max_output_tokens=4000,
    )


def test_role_route_is_explicit_before_fingerprinting():
    policy = ModelRoutingPolicy(Settings())
    normal = policy.route(request("researcher.research"))
    assert normal.model_hint == "deepseek-flash"
    assert normal.thinking_enabled is False
    for role in ("verifier.verify", "analyst.analyze", "analyst.decompose"):
        critical = policy.route(request(role))
        assert critical.model_hint == "deepseek-v4-pro"
        assert critical.thinking_enabled is True
        assert critical.reasoning_effort == "high"
    forced = ModelRoutingPolicy(Settings(model="deepseek-flash", model_force_single=True))
    assert forced.route(request("verifier.verify")).model_hint == "deepseek-flash"
    assert forced.route(request("verifier.verify")).thinking_enabled is False


@pytest.mark.asyncio
async def test_thinking_uses_content_only_and_omits_temperature():
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content=json.dumps({"answer": "final"}),
                        reasoning_content='{"answer":"NOT_FINAL"}',
                    ),
                )
            ]
        )

    adapter = OpenAICompatibleModelAdapter(
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        provider="deepseek",
        default_model="deepseek-flash",
        thinking_enabled=False,
    )
    result = await adapter.generate(
        ModelRoutingPolicy(Settings()).route(request("verifier.verify"))
    )
    assert result.output.answer == "final"
    assert "temperature" not in calls[0]
    assert calls[0]["extra_body"]["thinking"]["type"] == "enabled"
    assert calls[0]["reasoning_effort"] == "high"
    assert calls[0]["response_format"] == {"type": "json_object"}
