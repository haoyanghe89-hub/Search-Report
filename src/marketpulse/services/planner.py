from __future__ import annotations

import json

from marketpulse.agents.factory import AgentRunner
from marketpulse.agents.prompts import PLANNER_INSTRUCTIONS
from marketpulse.domain.research import ResearchPlan
from marketpulse.errors import InvalidInputError


def validate_topic(topic: str) -> str:
    cleaned = " ".join(topic.split())
    if len(cleaned) < 2:
        raise InvalidInputError("产品方向至少需要 2 个字符。")
    if len(cleaned) > 200:
        raise InvalidInputError("产品方向不能超过 200 个字符。")
    return cleaned


async def create_research_plan(
    topic: str, competitor_limit: int, runner: AgentRunner
) -> ResearchPlan:
    cleaned = validate_topic(topic)
    prompt = json.dumps(
        {
            "topic": cleaned,
            "market": "global",
            "search_language": "English",
            "competitor_candidate_limit": competitor_limit,
            "max_queries": 8,
        },
        ensure_ascii=False,
    )
    plan = await runner.run_json(
        name="MarketPulse Master",
        instructions=PLANNER_INSTRUCTIONS,
        prompt=prompt,
        schema=ResearchPlan,
    )
    return plan.model_copy(update={"original_topic": cleaned})
