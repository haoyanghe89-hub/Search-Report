from __future__ import annotations

from datetime import UTC, datetime

from marketpulse.adapters.fetch import FetchedPage
from marketpulse.domain.analysis import (
    Competitor,
    MarketAnalysis,
    MarketSignal,
    Pricing,
    Recommendation,
)
from marketpulse.domain.research import ResearchPlan, SearchCandidate, SearchQuery
from marketpulse.services.evidence_store import EvidenceStore
from marketpulse.services.extractor import build_page_evidence, extract_visible_text
from marketpulse.services.quality import evaluate_quality
from marketpulse.services.reporter import render_report


def make_page() -> FetchedPage:
    candidate = SearchCandidate(
        query_id="q1",
        title="Acme Pricing",
        url="https://acme.example/pricing",
        rank=1,
        source_hint="official",
    )
    body = b"""
    <html><script>secret()</script><nav>menu</nav><main>
    <h1>Acme plans and pricing</h1>
    <p>Professional teams pay $20 per user per month for transcription and summaries.</p>
    <p>The product integrates with calendar and video meeting platforms.</p>
    </main></html>
    """
    return FetchedPage(
        candidate=candidate,
        final_url="https://acme.example/pricing",
        content_type="text/html",
        body=body,
        fetched_at=datetime(2026, 9, 17, tzinfo=UTC),
    )


def test_extract_visible_text_removes_script_and_navigation() -> None:
    text = extract_visible_text(make_page())
    assert "secret" not in text
    assert "menu" not in text
    assert "$20 per user" in text


def test_render_report_has_ten_fixed_sections() -> None:
    store = EvidenceStore()
    store.add(build_page_evidence(make_page(), 1))
    bundle = store.bundle()
    coverage = store.coverage()
    plan = ResearchPlan(
        original_topic="AI meeting notes",
        normalized_topic="AI meeting notes tools",
        research_questions=["demand", "competitors", "pricing"],
        queries=[
            SearchQuery(id="q1", text="AI meeting notes market", intent="demand"),
            SearchQuery(id="q2", text="AI meeting notes competitors", intent="competitor"),
            SearchQuery(id="q3", text="AI meeting notes features", intent="product"),
            SearchQuery(id="q4", text="AI meeting notes pricing", intent="pricing"),
        ],
    )
    analysis = MarketAnalysis(
        executive_summary="这是一个有需求但竞争激烈的市场。",
        market_signals=[
            MarketSignal(
                statement="存在按席位订阅。",
                interpretation="商业模式成熟。",
                source_ids=["S1"],
            )
        ],
        competitors=[
            Competitor(
                name="Acme",
                positioning="会议纪要",
                target_customers="专业团队",
                key_features=["转录", "摘要"],
                pricing=Pricing(summary="$20/user/month", source_ids=["S1"], verified=True),
                source_ids=["S1"],
            )
        ],
        opportunities=["垂直场景"],
        barriers=["成熟竞品"],
        recommendation=Recommendation.CONDITIONAL_GO,
        confidence=0.5,
        rationale=["有需求", "可订阅", "竞争激烈"],
        risks=["同质化"],
        next_steps=["访谈 10 位客户"],
        limitations=["样本有限"],
    )
    quality = evaluate_quality(bundle, coverage, analysis)
    report = render_report(plan, bundle, coverage, analysis, quality)
    assert report.count("\n## ") == 10
    assert "## 9. 来源清单" in report
    assert "Conditional Go" in report
