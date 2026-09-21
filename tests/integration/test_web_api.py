from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from marketpulse.config import Settings
from marketpulse.domain.analysis import (
    Competitor,
    MarketAnalysis,
    MarketSignal,
    Pricing,
    QualityResult,
    Recommendation,
)
from marketpulse.domain.collaboration import BlackboardState
from marketpulse.domain.evidence import CoverageSummary, EvidenceBundle, Source, SourceType
from marketpulse.observability import RunStats
from marketpulse.services.blackboard import BlackboardStore
from marketpulse.web_api import app
from marketpulse.workflow import MarketPulseResult


def _result(tmp_path: Path) -> MarketPulseResult:
    source = Source(
        id="S1",
        url="https://example.com/pricing",
        title="Acme pricing",
        domain="example.com",
        source_type=SourceType.OFFICIAL,
        accessed_at=datetime(2026, 9, 17, tzinfo=UTC),
        query_id="q1",
    )
    analysis = MarketAnalysis(
        executive_summary="市场成熟，但需要垂直差异化。",
        market_signals=[
            MarketSignal(
                statement="存在公开订阅价格。",
                interpretation="用户已经形成付费预期。",
                source_ids=["S1"],
            )
        ],
        competitors=[
            Competitor(
                name="Acme",
                positioning="团队会议助手",
                target_customers="中小团队",
                key_features=["转录", "摘要"],
                pricing=Pricing(summary="$20/month", source_ids=["S1"], verified=True),
                source_ids=["S1"],
            )
        ],
        opportunities=["垂直工作流"],
        barriers=["同质化竞争"],
        recommendation=Recommendation.CONDITIONAL_GO,
        confidence=0.78,
        rationale=["需求明确", "付费存在", "需要差异化"],
        risks=["获客成本"],
        next_steps=["完成 10 次访谈"],
    )
    return MarketPulseResult(
        run_id="run_web_test",
        report_path=tmp_path / "report.md",
        quality=QualityResult(passed=True),
        stats=RunStats(run_id="run_web_test", sources=1),
        analysis=analysis,
        evidence=EvidenceBundle(sources=[source]),
        coverage=CoverageSummary(
            unique_sources=1,
            official_sources=1,
            claim_count=3,
            pricing_claims=1,
            low_coverage=True,
        ),
        report_markdown="# 测试报告",
    )


@pytest.mark.asyncio
async def test_health() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_read_committed_blackboard_and_events() -> None:
    settings = Settings.from_env(require_api_key=False)
    board = BlackboardStore(settings.database_url.get_secret_value())
    state = BlackboardState(run_id="run_api", topic="AI meeting tools", competitor_limit=3)
    board.create(state)
    state.warnings.append("missing evidence")
    board.save(state, "master", "review.completed")
    board.close()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        snapshot = await client.get("/api/runs/run_api")
        history = await client.get("/api/runs/run_api/events?after_version=0")
        missing = await client.get("/api/runs/missing")
    assert snapshot.json()["version"] == 1
    assert snapshot.json()["warnings"] == ["missing evidence"]
    assert len(history.json()) == 1
    assert history.json()[0]["actor"] == "master"
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_create_report_returns_structured_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_run_topic(_: object) -> MarketPulseResult:
        return _result(tmp_path)

    monkeypatch.setattr("marketpulse.web_api._run_topic", fake_run_topic)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/reports",
            json={"topic": "AI meeting notes tools", "competitor_limit": 5},
        )
    body = response.json()
    assert response.status_code == 200
    assert body["analysis"]["recommendation"] == "Conditional Go"
    assert body["sources"][0]["id"] == "S1"
    assert body["report_markdown"] == "# 测试报告"
