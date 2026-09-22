"""Deterministic report rendering and content hashing."""

from __future__ import annotations

from marketpulse.investigation.reporting.hashing import canonical_hash
from marketpulse.investigation.reporting.models import Citation
from marketpulse.investigation.reporting.writer import ReportDraft, SectionStatus

REPORT_HASH_DOMAIN = "phase5-report-v1"
CITATION_SET_HASH_DOMAIN = "phase5-citation-set-v1"


def compute_report_hash(draft: ReportDraft) -> str:
    return canonical_hash(
        REPORT_HASH_DOMAIN,
        {
            "report_type": draft.report_type,
            "schema_version": draft.schema_version,
            "sections": [
                {
                    "section_key": section.section_key,
                    "status": section.status,
                    "units": [
                        {
                            "unit_key": unit.unit_key,
                            "text": unit.text,
                            "content_class": unit.content_class,
                            "claim_refs": list(unit.claim_refs),
                            "evidence_intents": list(unit.evidence_intents),
                        }
                        for unit in section.units
                    ],
                }
                for section in draft.sections
            ],
        },
    )


def compute_citation_set_hash(citations: list[Citation]) -> str:
    return canonical_hash(
        CITATION_SET_HASH_DOMAIN,
        sorted(citation.citation_hash for citation in citations),
    )


def render_markdown(draft: ReportDraft, citations: list[Citation]) -> str:
    by_unit: dict[tuple[str, str], list[Citation]] = {}
    for citation in citations:
        by_unit.setdefault((citation.section_key, citation.unit_key), []).append(citation)

    lines: list[str] = []
    for section in draft.sections:
        lines.append(f"## {section.section_key.replace('_', ' ').title()}")
        lines.append("")
        if section.status is not SectionStatus.CONTENT:
            lines.append(f"_{section.status.replace('_', ' ').title()}_")
            lines.append("")
            continue
        for unit in section.units:
            refs = by_unit.get((section.section_key, unit.unit_key), [])
            suffix = "".join(f" [{citation.display_ordinal + 1}]" for citation in refs)
            lines.append(f"{unit.text}{suffix}")
            lines.append("")
    if citations:
        lines.append("## Citations")
        lines.append("")
        for citation in sorted(citations, key=lambda item: item.display_ordinal):
            lines.append(
                f"[{citation.display_ordinal + 1}] claim `{citation.claim_semantic_hash[:12]}` "
                f"evidence `{citation.evidence_semantic_hash[:12]}` "
                f"locator `{citation.canonical_locator.get('locator_type', 'TEXT_RANGE')}`"
            )
            lines.append("")
    return chr(10).join(lines).strip() + chr(10)


def render_json(draft: ReportDraft, citations: list[Citation]) -> dict[str, object]:
    by_unit: dict[tuple[str, str], list[int]] = {}
    for citation in citations:
        by_unit.setdefault((citation.section_key, citation.unit_key), []).append(
            citation.display_ordinal
        )
    return {
        "report_type": str(draft.report_type),
        "schema_version": draft.schema_version,
        "sections": [
            {
                "section_key": section.section_key,
                "status": str(section.status),
                "units": [
                    {
                        "unit_key": unit.unit_key,
                        "text": unit.text,
                        "content_class": str(unit.content_class),
                        "claim_refs": list(unit.claim_refs),
                        "citation_ordinals": sorted(
                            by_unit.get((section.section_key, unit.unit_key), [])
                        ),
                    }
                    for unit in section.units
                ],
            }
            for section in draft.sections
        ],
        "citation_count": len(citations),
    }
