"""Reuse exact semantic pairs, never reuse a final validation verdict."""

import json

from marketpulse.investigation.agents.contracts import (
    SemanticJudgment,
    VerificationInput,
    VerificationProposal,
)


def _pairs(request: VerificationInput) -> dict[tuple[str, str], str]:
    evidence = {e.evidence_key: e for e in request.evidence}
    output = {}
    for claim in request.claims:
        for key in (*claim.supporting_evidence_keys, *claim.contradicting_evidence_keys):
            if key not in evidence:
                continue
            payload = {
                "claim": claim.model_dump(
                    mode="json", exclude={"supporting_evidence_keys", "contradicting_evidence_keys"}
                ),
                "evidence": evidence[key].model_dump(mode="json"),
                "evidence_provenance": request.evidence_provenance.get(key),
            }
            output[(claim.claim_key, key)] = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return output


def reusable_judgments(
    current: VerificationInput,
    prior: tuple[tuple[VerificationInput, VerificationProposal], ...],
) -> tuple[SemanticJudgment, ...]:
    wanted = _pairs(current)
    matches: dict[tuple[str, str], SemanticJudgment] = {}
    for request, proposal in prior:
        previous = _pairs(request)
        for judgment in proposal.judgments:
            pair = (judgment.claim_key, judgment.evidence_key)
            if pair in wanted and wanted[pair] == previous.get(pair):
                matches[pair] = judgment
    # Reuse only complete claim batches. Missing/new support receives a fresh call;
    # this cannot omit a contradictory or otherwise newly linked evidence item.
    complete = {
        claim.claim_key
        for claim in current.claims
        if (keys := {pair for pair in wanted if pair[0] == claim.claim_key})
        and keys <= matches.keys()
    }
    return tuple(matches[pair] for pair in sorted(matches) if pair[0] in complete)
