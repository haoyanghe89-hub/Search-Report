"""Provider-independent Investigation domain contracts."""

from marketpulse.investigation.domain.claims import (
    Claim,
    ClaimEvidenceRelation,
    ConflictSet,
    ResearchGap,
    TimelineEvent,
    ValidationResult,
)
from marketpulse.investigation.domain.recordings import RecordedModelCall, RecordedToolCall
from marketpulse.investigation.domain.reports import (
    AuditEvent,
    Report,
    ReportSection,
    ReviewDecision,
)
from marketpulse.investigation.domain.runtime import (
    ExecutionStep,
    Investigation,
    InvestigationRun,
    ResearchTask,
)
from marketpulse.investigation.domain.sources import (
    DocumentArtifact,
    Evidence,
    Source,
    SourceSnapshot,
)

__all__ = [
    "AuditEvent",
    "Claim",
    "ClaimEvidenceRelation",
    "ConflictSet",
    "DocumentArtifact",
    "Evidence",
    "ExecutionStep",
    "Investigation",
    "InvestigationRun",
    "RecordedModelCall",
    "RecordedToolCall",
    "Report",
    "ReportSection",
    "ResearchGap",
    "ResearchTask",
    "ReviewDecision",
    "Source",
    "SourceSnapshot",
    "TimelineEvent",
    "ValidationResult",
]
