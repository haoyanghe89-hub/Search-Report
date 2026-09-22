from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from marketpulse.investigation.agents.contracts import (
    ClaimCandidate,
    EvidenceCandidate,
    QueryIntent,
)
from marketpulse.investigation.domain.claims import Claim
from marketpulse.investigation.domain.sources import DocumentArtifact, Evidence, SourceSnapshot
from marketpulse.investigation.validation.integrity import EvidenceIntegrityValidator
from marketpulse.investigation.validation.models import (
    AtomicityAssessment,
    ClaimNormalizationProposal,
)
from marketpulse.investigation.validation.normalization import ClaimNormalizer


class ProposalGuardError(ValueError):
    code = "INVALID_AGENT_PROPOSAL"


def stable_id(prefix: str, *parts: str) -> str:
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def normalize_query(query: str) -> str:
    return " ".join(query.casefold().split())


class QueryGuard:
    def __init__(self, *, max_length: int = 500) -> None:
        self.max_length = max_length

    def validate(
        self,
        intent: QueryIntent,
        *,
        task_key: str,
        target_text: str,
        purpose: str,
        executed_normalized: set[str],
        task_queries: set[str],
        remaining_budget: int,
    ) -> str:
        normalized = normalize_query(intent.query)
        if not normalized:
            raise ProposalGuardError("query is empty")
        if len(intent.query) > self.max_length:
            raise ProposalGuardError("query exceeds deterministic length limit")
        if remaining_budget <= 0:
            raise ProposalGuardError("query budget is exhausted")
        if normalized in executed_normalized:
            raise ProposalGuardError("normalized duplicate query")
        if normalized in task_queries:
            raise ProposalGuardError(f"same task repeated query: {task_key}")
        query_tokens = self._tokens(normalized)
        anchor_tokens = self._tokens(f"{target_text} {purpose}")
        if len(query_tokens) >= 3 and anchor_tokens and not query_tokens & anchor_tokens:
            if not intent.source_or_domain_hints:
                raise ProposalGuardError("query is obviously unrelated to task anchors")
        return normalized

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[\w-]+", value.casefold(), flags=re.UNICODE)
            if len(token) >= 3
        }


class EvidenceCreationGuard:
    def __init__(self, validator: EvidenceIntegrityValidator) -> None:
        self._validator = validator

    def create(
        self,
        candidate: EvidenceCandidate,
        *,
        run_id: str,
        artifact: DocumentArtifact,
        snapshot: SourceSnapshot,
        created_by_step_id: str,
        research_task_id: str,
        extracted_at: datetime,
    ) -> Evidence:
        quote_hash = hashlib.sha256(candidate.quote.encode("utf-8")).hexdigest()
        if candidate.quote_hash is not None and candidate.quote_hash != quote_hash:
            raise ProposalGuardError("candidate quote_hash does not match quote")
        if candidate.locator.quote_hash != quote_hash:
            raise ProposalGuardError("locator quote_hash does not match quote")
        evidence = Evidence(
            evidence_id=stable_id(
                "E", run_id, candidate.evidence_key, artifact.artifact_id, quote_hash
            ),
            run_id=run_id,
            snapshot_id=snapshot.snapshot_id,
            artifact_id=artifact.artifact_id,
            content=candidate.quote,
            content_hash=quote_hash,
            locator=candidate.locator,
            extracted_at=extracted_at,
            extractor_name="ModelAnalystAgent",
            extractor_version="phase43-v1",
            created_by_step_id=created_by_step_id,
            research_task_id=research_task_id,
        )
        integrity = self._validator.validate(
            evidence=evidence,
            snapshot=snapshot,
            artifact=artifact,
        )
        if not integrity.valid:
            failures = ",".join(item.code.value for item in integrity.failures)
            raise ProposalGuardError(f"candidate Evidence failed integrity: {failures}")
        return evidence


@dataclass(frozen=True, slots=True)
class ClaimMaterialization:
    claim: Claim
    reused: bool


class ClaimGuard:
    def __init__(self, normalizer: ClaimNormalizer | None = None) -> None:
        self._normalizer = normalizer or ClaimNormalizer()

    def materialize(
        self,
        candidate: ClaimCandidate,
        *,
        investigation_id: str,
        run_id: str,
        existing_claims: tuple[Claim, ...],
        created_by_step_id: str,
        research_task_id: str,
        now: datetime,
    ) -> ClaimMaterialization:
        proposal = ClaimNormalizationProposal(
            canonical_statement=candidate.canonical_statement or candidate.statement,
            entity_qualifiers=candidate.entity_qualifiers,
            time_qualifiers=candidate.time_qualifiers,
            scope_qualifiers=candidate.scope_qualifiers,
            claim_type=candidate.claim_type,
            importance=candidate.importance,
            critical=candidate.critical,
            atomicity=AtomicityAssessment(
                is_atomic=candidate.atomicity.is_atomic,
                issues=candidate.atomicity.issues,
                proposed_atomic_statements=candidate.atomicity.proposed_atomic_statements,
            ),
        )
        normalized = self._normalizer.normalize(proposal)
        if not normalized.accepted:
            raise ProposalGuardError("; ".join(normalized.rejection_reasons))
        qualifiers = {
            **candidate.entity_qualifiers,
            **candidate.time_qualifiers,
            **candidate.scope_qualifiers,
            **normalized.qualifiers,
        }
        key = self.dedup_key(
            normalized.canonical_statement,
            normalized.claim_type.value,
            qualifiers,
        )
        for claim in existing_claims:
            if self.dedup_key(claim.statement, claim.claim_type.value, claim.qualifiers) == key:
                return ClaimMaterialization(claim=claim, reused=True)
        claim = Claim(
            claim_id=stable_id("C", run_id, key),
            investigation_id=investigation_id,
            run_id=run_id,
            statement=normalized.canonical_statement,
            claim_type=normalized.claim_type,
            qualifiers=qualifiers,
            importance=normalized.importance,
            is_critical=normalized.critical,
            created_by_step_id=created_by_step_id,
            research_task_id=research_task_id,
            created_at=now,
            updated_at=now,
        )
        return ClaimMaterialization(claim=claim, reused=False)

    @staticmethod
    def dedup_key(statement: str, claim_type: str, qualifiers: Mapping[str, object]) -> str:
        payload = json.dumps(
            {
                "statement": " ".join(statement.casefold().split()),
                "claim_type": claim_type,
                "qualifiers": qualifiers,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
