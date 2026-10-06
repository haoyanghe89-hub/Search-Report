"""Compare captured LIVE analysis JSON with strict and lossless-normalized parsing."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from diagnose_token_flow import blob
from pydantic import ValidationError
from sqlalchemy import create_engine

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.adapters.model import _json_payload
from marketpulse.investigation.agents.contracts import (
    AnalysisInput,
    AnalysisProposal,
    ClaimCandidate,
    validate_agent_proposal,
)
from marketpulse.investigation.agents.model_agents import ModelAnalystAgent
from marketpulse.investigation.agents.normalization import normalize_existing_claim_references
from marketpulse.investigation.feedback.context import claim_key
from marketpulse.investigation.feedback.guards import (
    ClaimGuard,
    EvidenceCreationGuard,
    ProposalGuardError,
)
from marketpulse.investigation.feedback.store import FeedbackStore
from marketpulse.investigation.persistence.base import create_session_factory
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.validation.integrity import EvidenceIntegrityValidator
from marketpulse.investigation.validation.models import RecognizedArtifactVersions


async def diagnose(root: Path) -> None:
    with sqlite3.connect(f"file:{(root / 'live.db').as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM inv_recorded_model_calls WHERE prompt_version LIKE '%:analyst.analyze' "
            "ORDER BY recorded_at"
        ).fetchall()
    files = await asyncio.to_thread(lambda: sorted(root.glob("analysis-raw-*.json")))
    if len(files) != len(rows):
        raise ValueError("analysis response capture is incomplete; cannot correlate by call order")
    engine = create_engine(f"sqlite:///file:{(root / 'live.db').as_posix()}?mode=ro&uri=true")
    sessions = create_session_factory(engine)
    repository = InvestigationRepository(sessions)
    state = FeedbackStore(sessions, repository).state(rows[0]["run_id"])
    blobs = LocalContentAddressedBlobStorage(root / "blobs")
    integrity = EvidenceIntegrityValidator(
        blobs=blobs,
        recognized_versions=RecognizedArtifactVersions(
            snapshot_parsers=frozenset(
                {
                    ("html", "1", "text-normalizer-v1"),
                    ("html", "2", "text-normalizer-v1"),
                    ("plain-text", "1", "text-normalizer-v1"),
                    ("pypdf-text-layer", "1", "text-normalizer-v1"),
                }
            ),
            artifact_processors=frozenset(
                {("html", "1"), ("html", "2"), ("plain-text", "1"), ("pypdf-text-layer", "1")}
            ),
        ),
    )
    snapshots = {s.snapshot_id: s for s in state.snapshots}
    results = []
    for path, row in zip(files, rows, strict=True):
        request = blob(root / "blobs/sha256", row["request_blob_ref"])["request"]
        context = AnalysisInput.model_validate(
            json.loads(request["messages"][1]["content"])["bounded_context"]
        )
        raw = json.loads(path.read_text(encoding="utf-8"))["raw_content"]
        payload = json.loads(_json_payload(raw))
        entry = {"file": path.name, "call_id": row["call_id"], "before_errors": []}
        try:
            AnalysisProposal.model_validate(payload)
        except ValidationError as error:
            entry["before_errors"] = error.errors(include_input=False, include_context=False)
        normalized = normalize_existing_claim_references(payload, context)
        entry["known_claim_refs_added"] = sorted(
            {c["claim_key"] for c in normalized.get("claims", [])}
            - {c["claim_key"] for c in payload.get("claims", [])}
        )
        try:
            proposal = AnalysisProposal.model_validate(normalized)
            validate_agent_proposal(context, proposal)
            agent = ModelAnalystAgent(
                SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(output=proposal)))
            )
            grounded = await agent.analyze(context, ground_quotes=True)
            entry["after_structure_and_references"] = "PASS"
            entry["quote_grounding"] = agent.grounding_diagnostics
            outcomes = {}
            views = {v.artifact_key: v for v in context.artifacts}
            for candidate in grounded.evidence:
                view = views[candidate.artifact_key]
                artifact = next(
                    a
                    for a in state.artifacts
                    if (
                        a.sha256 == view.content_hash
                        and snapshots[a.snapshot_id].source_id == view.source_key
                        and f"SNAP-{snapshots[a.snapshot_id].raw_sha256[:24]}" == view.snapshot_key
                        and (a.page_number or None) == getattr(view.locator, "page", None)
                    )
                )
                try:
                    EvidenceCreationGuard(integrity).create(
                        candidate,
                        run_id=state.run.run_id,
                        artifact=artifact,
                        snapshot=snapshots[artifact.snapshot_id],
                        created_by_step_id="diagnostic",
                        research_task_id="diagnostic",
                        extracted_at=datetime.now(UTC),
                    )
                    outcomes[candidate.evidence_key] = "PASS"
                except ProposalGuardError as error:
                    outcomes[candidate.evidence_key] = str(error)
            entry["archive_integrity_guard"] = outcomes
        except ValueError as error:
            entry["after_structure_and_references"] = type(error).__name__
        results.append(entry)
    output = root / "analysis-normalization-comparison.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    identities = []
    for claim in state.claims:
        candidate = ClaimCandidate(
            claim_key=claim_key(claim),
            statement=claim.statement,
            claim_type=claim.claim_type,
            **{f"{g}_qualifiers": claim.qualifiers[g] for g in ("entity", "time", "scope")},
        )
        result = ClaimGuard().materialize(
            candidate,
            investigation_id=claim.investigation_id,
            run_id=claim.run_id,
            existing_claims=state.claims,
            created_by_step_id="diagnostic",
            research_task_id="diagnostic",
            now=datetime.now(UTC),
        )
        identities.append(
            {
                "claim_id": claim.claim_id,
                "reused_unchanged": result.reused and result.claim == claim,
                "qualifier_groups_unchanged": {
                    group: getattr(candidate, f"{group}_qualifiers")
                    == result.claim.qualifiers[group]
                    == claim.qualifiers[group]
                    for group in ("entity", "time", "scope")
                },
            }
        )
    (root / "claim-identity-proof.json").write_text(
        json.dumps(identities, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    engine.dispose()
    print(json.dumps({"calls": len(results), "output": str(output)}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    asyncio.run(diagnose(parser.parse_args().root))


if __name__ == "__main__":
    main()
