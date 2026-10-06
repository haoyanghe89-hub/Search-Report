"""Disjoint claim batches verified concurrently; final verdicts stay in deterministic policy."""

from collections.abc import Callable

from marketpulse.investigation.agents.contracts import (
    VerificationInput,
    VerificationProposal,
    validate_agent_proposal,
)
from marketpulse.investigation.agents.model_agents import ModelVerifierAgent
from marketpulse.investigation.feedback.parallel import bounded_map
from marketpulse.investigation.ports.external import ModelPort


async def verification_team(
    request: VerificationInput,
    port: Callable[[str], ModelPort],
    *,
    workers: int,
    evidence_sources: dict[str, str] | None = None,
) -> VerificationProposal:
    original = request
    claim_keys = {c.claim_key: f"C{i + 1}" for i, c in enumerate(request.claims)}
    evidence_keys = {e.evidence_key: f"E{i + 1}" for i, e in enumerate(request.evidence)}
    request = request.model_copy(
        update={
            "evidence_provenance": {
                evidence_keys[k]: v
                for k, v in request.evidence_provenance.items()
                if k in evidence_keys
            },
            "claims": tuple(
                c.model_copy(
                    update={
                        "claim_key": claim_keys[c.claim_key],
                        "supporting_evidence_keys": tuple(
                            evidence_keys[k] for k in c.supporting_evidence_keys
                        ),
                        "contradicting_evidence_keys": tuple(
                            evidence_keys[k] for k in c.contradicting_evidence_keys
                        ),
                    }
                )
                for c in request.claims
            ),
            "evidence": tuple(
                e.model_copy(update={"evidence_key": evidence_keys[e.evidence_key]})
                for e in request.evidence
            ),
        }
    )
    count = min(workers, len(request.claims))
    if not count:
        return VerificationProposal()

    async def verify(index: int) -> VerificationProposal:
        claims = request.claims[index::count]
        keys = {
            key
            for c in claims
            for key in (*c.supporting_evidence_keys, *c.contradicting_evidence_keys)
        }
        subset = request.model_copy(
            update={
                "claims": claims,
                "evidence": tuple(e for e in request.evidence if e.evidence_key in keys),
                "evidence_provenance": {
                    k: v for k, v in request.evidence_provenance.items() if k in keys
                },
            }
        )
        if evidence_sources is not None:
            source_ids = {
                evidence_sources[key]
                for key, alias in evidence_keys.items()
                if alias in keys and key in evidence_sources
            }
            families = tuple(
                f for f in request.source_families if source_ids.intersection(f.source_keys)
            )
            subset = subset.model_copy(
                update={
                    "source_families": families,
                    "source_independence_keys": tuple(f.family_key for f in families),
                }
            )
        return await ModelVerifierAgent(port(f"verifier.batch-{index}")).verify(subset)

    proposals = await bounded_map(list(range(count)), verify, count)
    merged = VerificationProposal(
        judgments=tuple(item for p in proposals for item in p.judgments),
        gaps=tuple(item for p in proposals for item in p.gaps),
        contradiction_interpretations=tuple(
            item for p in proposals for item in p.contradiction_interpretations
        ),
        conflict_explanations=tuple(item for p in proposals for item in p.conflict_explanations),
        suggested_research_directions=tuple(
            dict.fromkeys(item for p in proposals for item in p.suggested_research_directions)
        ),
        qualifier_supplements=tuple(item for p in proposals for item in p.qualifier_supplements),
    )
    claims = {v: k for k, v in claim_keys.items()}
    evidence = {v: k for k, v in evidence_keys.items()}
    restored = merged.model_copy(
        update={
            "qualifier_supplements": tuple(
                s.model_copy(
                    update={
                        "claim_key": claims[s.claim_key],
                        "evidence_key": evidence[s.evidence_key],
                    }
                )
                for s in merged.qualifier_supplements
            ),
            "judgments": tuple(
                j.model_copy(
                    update={
                        "claim_key": claims[j.claim_key],
                        "evidence_key": evidence[j.evidence_key],
                    }
                )
                for j in merged.judgments
            ),
            "gaps": tuple(
                g.model_copy(
                    update={
                        "target_claim_key": claims[g.target_claim_key]
                        if g.target_claim_key
                        else None
                    }
                )
                for g in merged.gaps
            ),
            "contradiction_interpretations": tuple(
                c.model_copy(
                    update={
                        "claim_key": claims[c.claim_key],
                        "evidence_keys": tuple(evidence[k] for k in c.evidence_keys),
                    }
                )
                for c in merged.contradiction_interpretations
            ),
        }
    )
    validate_agent_proposal(original, restored)
    return restored
