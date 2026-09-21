from __future__ import annotations

import json

from marketpulse.agents.factory import AgentRunner
from marketpulse.agents.prompts import ANALYZER_INSTRUCTIONS
from marketpulse.domain.analysis import MarketAnalysis
from marketpulse.domain.evidence import CoverageSummary, EvidenceBundle
from marketpulse.errors import NoUsableEvidenceError


async def analyze_market(
    topic: str,
    evidence: EvidenceBundle,
    coverage: CoverageSummary,
    competitor_limit: int,
    runner: AgentRunner,
) -> MarketAnalysis:
    if not evidence.sources or not evidence.claims:
        raise NoUsableEvidenceError("没有足够的页面正文证据可供分析。")
    payload = {
        "topic": topic,
        "market": "global",
        "report_language": "Chinese",
        "competitor_candidate_limit": competitor_limit,
        "coverage": coverage.model_dump(mode="json"),
        "sources": [source.model_dump(mode="json") for source in evidence.sources],
        "claims": [claim.model_dump(mode="json") for claim in evidence.claims],
        "warnings": evidence.warnings,
    }
    analysis = await runner.run_json(
        name="MarketPulse Analyst",
        instructions=ANALYZER_INSTRUCTIONS,
        prompt=json.dumps(payload, ensure_ascii=False),
        schema=MarketAnalysis,
    )
    known_ids = {source.id for source in evidence.sources}
    cited_ids = {
        source_id for signal in analysis.market_signals for source_id in signal.source_ids
    } | {
        source_id
        for competitor in analysis.competitors
        for source_id in competitor.source_ids + competitor.pricing.source_ids
    }
    unknown = cited_ids - known_ids
    if unknown:
        raise NoUsableEvidenceError(f"分析引用了未知来源: {sorted(unknown)}")
    updates: dict[str, object] = {}
    if coverage.low_coverage and analysis.confidence > 0.55:
        updates["confidence"] = 0.55
    if coverage.low_coverage:
        updates["limitations"] = list(
            dict.fromkeys([*analysis.limitations, "来源覆盖不足，结论置信度已下调。"])
        )
    return analysis.model_copy(update=updates)
