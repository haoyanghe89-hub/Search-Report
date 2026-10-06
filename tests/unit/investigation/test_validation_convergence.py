from types import SimpleNamespace

import pytest

from marketpulse.investigation.agents.contracts import AnalysisInput, AnalysisProposal
from marketpulse.investigation.agents.normalization import normalize_existing_claim_references
from marketpulse.investigation.domain.enums import ClaimType, SemanticJudgmentStatus
from marketpulse.investigation.validation.profiles import PROFILES, ProfileContext


def context(
    qualifiers, *, count=2, score=0.8, entails=True, strong=False, kind=ClaimType.QUANTITATIVE
):
    return ProfileContext(
        claim=SimpleNamespace(qualifiers=qualifiers, importance="HIGH", claim_type=kind),
        judgments=tuple(
            SimpleNamespace(
                evidence_id=f"E{i}",
                judgment=SemanticJudgmentStatus.ENTAILS
                if entails
                else SemanticJudgmentStatus.PARTIALLY_SUPPORTS,
            )
            for i in range(count)
        ),
        evidence_to_source={f"E{i}": f"S{i}" for i in range(count)},
        source_by_id={
            f"S{i}": SimpleNamespace(
                source_id=f"S{i}", is_first_hand=True, source_type="OFFICIAL_REPORT"
            )
            for i in range(count)
        },
        independence=SimpleNamespace(independent_family_count=count),
        quality_by_source={f"S{i}": SimpleNamespace(normalized_score=score) for i in range(count)},
        conflicts=(),
        strong_contradiction=SimpleNamespace(triggered=strong),
    )


COMPLETE = {
    "value": 0,
    "unit": "%",
    "time": "2026",
    "scope": "Benchmark A",
    "definition": "pass@1",
    "methodology": "documented test",
}


@pytest.mark.parametrize(
    "missing,status",
    [
        (None, "VERIFIED"),
        ("methodology", "PROBABLE"),
        ("unit", "UNVERIFIED"),
        ("value", "UNVERIFIED"),
        ("definition", "UNVERIFIED"),
    ],
)
def test_quantitative_grades_never_invent_core_fields(missing, status):
    fields = {k: v for k, v in COMPLETE.items() if k != missing}
    result = PROFILES[ClaimType.QUANTITATIVE].evaluate(context(fields))
    assert result.recommended_status == status
    if missing == "methodology":
        assert not result.sufficient
        assert "methodology_or_provenance" in result.missing_requirements


@pytest.mark.parametrize(
    "changes", [{"entails": False}, {"strong": True}, {"count": 0}, {"score": 0.25}]
)
def test_probable_requires_real_entailment_and_credible_support(changes):
    fields = {k: v for k, v in COMPLETE.items() if k != "methodology"}
    assert (
        PROFILES[ClaimType.QUANTITATIVE].evaluate(context(fields, **changes)).recommended_status
        == "UNVERIFIED"
    )


def test_group_containers_do_not_satisfy_missing_time_or_scope():
    result = PROFILES[ClaimType.QUANTITATIVE].evaluate(
        context({**COMPLETE, "time": {}, "scope": {}})
    )
    assert not result.sufficient
    assert {"qualifier:time", "qualifier:scope"} <= set(result.missing_requirements)


def test_supplied_qualifiers_are_normalized_without_fact_invention():
    payload = {
        "claims": [
            {
                "claim_key": "C1",
                "statement": "The reported score is zero.",
                "claim_type": "QUANTITATIVE",
                "qualifiers": {
                    "entity": {"numeric_value": 0, "unit": "%"},
                    "time": {"as_of": "2026"},
                    "scope": {"benchmark": "A", "metric": "pass@1", "method": "measured"},
                },
            }
        ]
    }
    normalized = normalize_existing_claim_references(payload, AnalysisInput(artifacts=()))
    claim = AnalysisProposal.model_validate(normalized).claims[0]
    assert claim.entity_qualifiers["value"] == 0
    assert claim.time_qualifiers["time"] == "2026"
    assert claim.scope_qualifiers["definition"] == "pass@1"
    assert claim.scope_qualifiers["methodology"] == "measured"
    assert "provenance" not in claim.scope_qualifiers
    assert payload["claims"][0]["qualifiers"]["entity"] == {"numeric_value": 0, "unit": "%"}


def test_probable_policy_retains_full_verification_distinction():
    from marketpulse.investigation.validation.policy import ValidationPolicy

    assert (
        ValidationPolicy._status(
            profile_status="PROBABLE", profile_sufficient=False, strong=False, conflicts=()
        ).value
        == "PROBABLE"
    )
    assert (
        ValidationPolicy._status(
            profile_status="VERIFIED", profile_sufficient=False, strong=False, conflicts=()
        ).value
        == "UNVERIFIED"
    )


def test_verification_budget_counts_inflight_and_leaves_report_reserve():
    from marketpulse.investigation.harness.stage_budget import VerificationBudgetPolicy

    policy = VerificationBudgetPolicy(max_calls=2, max_tokens=1000)
    assert policy.admits(calls=1, tokens=500, cost=100, inflight_calls=0, inflight_tokens=0)
    assert not policy.admits(calls=1, tokens=500, cost=100, inflight_calls=1, inflight_tokens=0)
    assert not policy.admits(calls=1, tokens=900, cost=100, inflight_calls=0, inflight_tokens=1)


def test_exact_issuer_hosts_do_not_promote_shared_hosts_or_legacy_guesses():
    from marketpulse.adapters.investigation_search import PublicSearchPortAdapter

    adapter = PublicSearchPortAdapter(None)
    assert adapter._publisher("https://deepmind.google/models/argon/") == "Google"
    assert adapter._publisher("https://deepmind.google.evil.test/fake") is None
    assert adapter._publisher("https://storage.googleapis.com/user-content/fake.pdf") is None
    assert adapter._publisher("http://deepmind.google/insecure") is None
    assert adapter._publisher("https://unrelated.test/official-google-report") is None


@pytest.mark.parametrize(
    "kind,fields",
    [
        (ClaimType.QUANTITATIVE, COMPLETE),
        (
            ClaimType.CAUSAL,
            {
                "temporal_ordering": True,
                "mechanism_support": True,
                "causal_attribution_evidence": True,
                "alternative_explanations_considered": True,
            },
        ),
        (
            ClaimType.ATTRIBUTION,
            {
                "attribution_kind": "REGULATORY_FINDING",
                "interested_party_only": False,
                "direct_finding": True,
            },
        ),
        (
            ClaimType.ANALYTIC_INFERENCE,
            {
                "reasoning_basis": "Two independent observations",
                "uncertainty": "Scope limited",
            },
        ),
        (
            ClaimType.INSTITUTIONAL_ACTION,
            {
                "actor": "Agency",
                "action": "Published",
                "scope": "A",
                "date": "2026",
            },
        ),
        (ClaimType.STATEMENT, {"speaker": "Agency"}),
        (ClaimType.IMPACT, {"impact_subtype": "OBSERVED_IMPACT"}),
    ],
)
def test_secondary_quality_tier_does_not_waive_semantic_core(kind, fields):
    result = PROFILES[kind].evaluate(context(fields, score=0.55, kind=kind))
    assert result.recommended_status == "PROBABLE"
    assert not result.sufficient
    assert (
        PROFILES[kind]
        .evaluate(context(fields, score=0.55, kind=kind, entails=False))
        .recommended_status
        == "UNVERIFIED"
    )
    assert (
        PROFILES[kind].evaluate(context(fields, score=0.55, kind=kind, count=1)).recommended_status
        == "UNVERIFIED"
    )


def test_new_qualifier_conflicts_are_not_silently_overwritten():
    from marketpulse.investigation.agents.normalization import normalize_new_claim_qualifiers

    with pytest.raises(ValueError, match="conflicting"):
        normalize_new_claim_qualifiers(
            {
                "qualifiers": {"entity": {"value": 77}},
                "entity_qualifiers": {"value": 78},
            }
        )


@pytest.mark.parametrize(
    "change", [None, "new_claim", "evidence", "conflict", "status", "fingerprint"]
)
def test_verification_convergence_requires_unchanged_complete_inputs(change):
    from datetime import UTC, datetime, timedelta

    from marketpulse.investigation.feedback.orchestrator import AgentFeedbackOrchestrator
    from marketpulse.investigation.validation.policy import ValidationPolicy

    now = datetime(2026, 10, 2, tzinfo=UTC)
    records = [
        SimpleNamespace(
            claim_id="C1",
            validation_id=f"V{i}",
            created_at=now + timedelta(seconds=i),
            policy_version=ValidationPolicy.VERSION,
            input_fingerprint="identical",
            status="UNVERIFIED",
            evidence_set_hash=ValidationPolicy._evidence_set_hash((), ()),
            conflict_set_refs=(),
            validation_basis_payload={"unresolved_conflict_ids": []},
        )
        for i in range(2)
    ]
    state = SimpleNamespace(
        claims=[SimpleNamespace(claim_id="C1")],
        validations=records,
        relations=(),
        evidence=(),
        conflicts=(),
    )
    if change == "new_claim":
        state.claims.append(SimpleNamespace(claim_id="C2"))
    elif change == "evidence":
        records[-1].evidence_set_hash = "outdated"
    elif change == "conflict":
        state.conflicts = (
            SimpleNamespace(
                conflict_id="X1",
                claim_ids=("C1",),
                resolution_status="UNRESOLVED",
            ),
        )
    elif change == "status":
        records[-1].status = "PROBABLE"
    elif change == "fingerprint":
        records[-1].input_fingerprint = "different"
    orchestrator = AgentFeedbackOrchestrator.__new__(AgentFeedbackOrchestrator)
    orchestrator.validation_policy = ValidationPolicy
    assert orchestrator._verification_converged(state) is (change is None)
