from __future__ import annotations

from marketpulse.domain.analysis import MarketAnalysis, QualityIssue, QualityResult
from marketpulse.domain.evidence import CoverageSummary, EvidenceBundle


def evaluate_quality(
    evidence: EvidenceBundle,
    coverage: CoverageSummary,
    analysis: MarketAnalysis,
) -> QualityResult:
    issues: list[QualityIssue] = []
    if not evidence.sources:
        issues.append(QualityIssue(code="no_sources", message="没有可用来源", fatal=True))
    if coverage.unique_sources < 8:
        issues.append(
            QualityIssue(
                code="few_sources",
                message=f"来源仅 {coverage.unique_sources} 个，低于目标 8 个",
            )
        )
    if coverage.official_sources < 3:
        issues.append(
            QualityIssue(
                code="few_official_sources",
                message=f"官方来源仅 {coverage.official_sources} 个，低于目标 3 个",
            )
        )
    if len(analysis.competitors) < 3:
        issues.append(
            QualityIssue(
                code="few_competitors",
                message=f"有证据支持的竞品仅 {len(analysis.competitors)} 个",
            )
        )
    if coverage.pricing_claims == 0:
        issues.append(QualityIssue(code="no_pricing", message="未验证到公开定价信息"))
    return QualityResult(passed=not any(issue.fatal for issue in issues), issues=issues)
