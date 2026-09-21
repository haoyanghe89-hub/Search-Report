from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from marketpulse.domain.analysis import MarketAnalysis, QualityResult
from marketpulse.domain.collaboration import ReportDraft, ReportParagraph
from marketpulse.domain.evidence import CoverageSummary, EvidenceBundle
from marketpulse.domain.research import ResearchPlan
from marketpulse.errors import OutputWriteError


def apply_report_draft(analysis: MarketAnalysis, draft: ReportDraft) -> MarketAnalysis:
    """Only editorial fields change. Factual tables and decision remain canonical."""

    def paragraph(value: ReportParagraph) -> str:
        links = " ".join(f"[{sid}](#{sid.lower()})" for sid in dict.fromkeys(value.source_ids))
        return f"{value.text} {links}"

    return analysis.model_copy(
        update={
            "executive_summary": paragraph(draft.executive_summary),
            "rationale": [paragraph(value) for value in draft.rationale],
            "next_steps": draft.next_steps,
            "limitations": list(dict.fromkeys([*analysis.limitations, *draft.limitations])),
        }
    )


def render_report(
    plan: ResearchPlan,
    evidence: EvidenceBundle,
    coverage: CoverageSummary,
    analysis: MarketAnalysis,
    quality: QualityResult,
    *,
    executed_query_count: int | None = None,
) -> str:
    environment = Environment(
        loader=PackageLoader("marketpulse", "templates"),
        autoescape=select_autoescape(default=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template("report.md.j2")
    return (
        template.render(
            plan=plan,
            evidence=evidence,
            coverage=coverage,
            analysis=analysis,
            quality=quality,
            research_date=date.today().isoformat(),
            executed_query_count=executed_query_count,
        ).strip()
        + "\n"
    )


def write_report_atomic(markdown: str, output_path: Path) -> Path:
    target = output_path.expanduser().resolve()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(markdown)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temp_name).replace(target)
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise OutputWriteError(f"无法写入报告 {target}: {exc}") from exc
    return target
