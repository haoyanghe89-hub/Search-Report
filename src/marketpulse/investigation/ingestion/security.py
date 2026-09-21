from __future__ import annotations

import re

from marketpulse.investigation.ingestion.models import UntrustedContentAssessment

DETECTOR_VERSION = "instruction-boundary-v1"
_PATTERNS = {
    "IGNORE_PRIOR_INSTRUCTIONS": re.compile(
        r"\b(?:ignore|disregard)\s+(?:all\s+)?(?:previous|prior)\s+instructions?\b", re.I
    ),
    "SYSTEM_PROMPT_REQUEST": re.compile(r"\b(?:reveal|show|print)\b.{0,30}\bsystem prompt\b", re.I),
    "ROLE_OVERRIDE": re.compile(r"\b(?:you are now|act as)\b", re.I),
    "TOOL_EXECUTION_INSTRUCTION": re.compile(
        r"\b(?:call|execute|invoke|run)\b.{0,30}\b(?:tool|command|shell)\b", re.I
    ),
}


def assess_untrusted_content(text: str) -> UntrustedContentAssessment:
    findings = tuple(code for code, pattern in _PATTERNS.items() if pattern.search(text))
    return UntrustedContentAssessment(
        detector_version=DETECTOR_VERSION,
        suspicious_instruction_detected=bool(findings),
        finding_codes=findings,
    )
