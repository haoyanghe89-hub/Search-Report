"""Duration presets constrain investment, never validation thresholds."""

from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketpulse.config import Settings
from marketpulse.investigation.persistence.models import AuditEventRow

Depth = Literal["quick", "standard", "deep"]
PRESETS = {
    "quick": dict(
        total_timeout_seconds=300,
        max_research_rounds=1,
        max_search_queries=12,
        max_pages=32,
        max_model_calls=40,
        max_tokens=300_000,
        analysis_max_sources=4,
        analysis_max_excerpts=8,
        analysis_max_chars=12_000,
        model_context_items=8,
        research_workers=2,
        max_queries_per_researcher=2,
    ),
    "standard": dict(
        total_timeout_seconds=600,
        max_research_rounds=3,
        max_search_queries=48,
        max_pages=80,
        max_model_calls=120,
        max_tokens=1_000_000,
        analysis_max_sources=8,
        analysis_max_excerpts=16,
        analysis_max_chars=24_000,
        model_context_items=16,
        research_workers=4,
        max_queries_per_researcher=3,
    ),
    "deep": dict(
        total_timeout_seconds=1800,
        max_research_rounds=6,
        max_search_queries=120,
        max_pages=160,
        max_model_calls=240,
        max_tokens=2_000_000,
        analysis_max_sources=12,
        analysis_max_excerpts=24,
        analysis_max_chars=40_000,
        model_context_items=24,
        research_workers=4,
        max_queries_per_researcher=3,
    ),
}
SOURCE_LIMITS = {"quick": 16, "standard": 40, "deep": 80}
FINALIZE_RESERVE_SECONDS = 30


def depth_settings(settings: Settings, depth: Depth) -> Settings:
    # Operator ceilings remain authoritative; selecting deep cannot enlarge them.
    updates = {name: min(getattr(settings, name), value) for name, value in PRESETS[depth].items()}
    updates["investigation_depth"] = depth
    return settings.model_copy(update=updates)


def selected_depth(session: Session, investigation_id: str) -> Depth:
    event = session.scalar(
        select(AuditEventRow).where(
            AuditEventRow.investigation_id == investigation_id,
            AuditEventRow.event_type == "INVESTIGATION_DEPTH_SELECTED",
        )
    )
    value = event.metadata_payload.get("depth") if event else None
    return value if value in PRESETS else "standard"
