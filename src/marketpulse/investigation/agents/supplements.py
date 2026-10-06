"""Literal, referenced qualifier corrections; semantic sufficiency remains policy-owned."""

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING

from pydantic import JsonValue

from marketpulse.investigation.domain.enums import SemanticJudgmentStatus

if TYPE_CHECKING:
    from marketpulse.investigation.agents.contracts import (
        QualifierSupplement,
        VerificationInput,
        VerificationProposal,
    )


def validate_supplements(request: "VerificationInput", proposal: "VerificationProposal") -> None:
    claims = {c.claim_key: c for c in request.claims}
    evidence = {e.evidence_key: e for e in request.evidence}
    seen = set()
    for item in proposal.qualifier_supplements:
        if item.claim_key not in claims or item.evidence_key not in evidence:
            raise ValueError("qualifier supplement references unknown material")
        claim = claims[item.claim_key]
        if item.evidence_key not in claim.supporting_evidence_keys:
            raise ValueError("qualifier supplement requires related supporting evidence")
        quote = evidence[item.evidence_key].quote
        if item.source_quote not in quote or item.value not in item.source_quote:
            raise ValueError("qualifier supplement value must be verbatim in its cited quote")
        group = (
            claim.time_qualifiers
            if item.field == "time"
            else claim.entity_qualifiers
            if item.field in {"value", "unit", "speaker"}
            else claim.scope_qualifiers
        )
        names = ("time", "as_of", "date") if item.field == "time" else (item.field,)
        if any(group.get(name) not in (None, "", {}, []) for name in names):
            raise ValueError("qualifier supplement cannot overwrite an existing qualifier")
        if item.field == "time":
            if not re.search(r"\b(?:19|20)\d{2}\b", item.value):
                raise ValueError("qualifier time requires an explicit dated value")
            pattern = (
                r"as of|results.{0,40}(?:as of|through)|截至|结果截止"
                if item.time_reference == "RESULTS_AS_OF"
                else r"evaluat(?:ed|ion).{0,40}(?:in|during|period)|测量期间|评测期间"
            )
            if item.time_reference is None or not re.search(pattern, item.source_quote, re.I):
                raise ValueError("qualifier time requires explicit evaluation/results date context")
        if not any(
            j.claim_key == item.claim_key
            and j.evidence_key == item.evidence_key
            and j.entailment is SemanticJudgmentStatus.ENTAILS
            for j in proposal.judgments
        ):
            raise ValueError("qualifier supplement requires exact full-claim ENTAILS")
        key = (item.claim_key, item.field)
        if key in seen:
            raise ValueError("qualifier supplement has duplicate or competing values")
        seen.add(key)


def supplemented_qualifiers(
    qualifiers: dict[str, JsonValue], supplements: Iterable["QualifierSupplement"]
) -> dict[str, JsonValue]:
    result = dict(qualifiers)
    for item in supplements:
        name = (
            "time"
            if item.field == "time"
            else "entity"
            if item.field in {"value", "unit", "speaker"}
            else "scope"
        )
        current = result.get(name, {})
        group = dict(current) if isinstance(current, dict) else {name: current}
        group[item.field] = item.value
        if item.field == "time":
            group["time_reference"] = item.time_reference
        result[name] = group
        if item.field not in {"time", "scope"}:
            result[item.field] = item.value
    return result
