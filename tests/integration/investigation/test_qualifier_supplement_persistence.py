import pytest
from sqlalchemy import select
from test_phase43_feedback_loop import INVESTIGATION_ID, NOW, _seed_investigation, _seed_run

from marketpulse.investigation.agents.contracts import QualifierSupplement
from marketpulse.investigation.domain.claims import Claim
from marketpulse.investigation.domain.enums import ClaimType, RunMode
from marketpulse.investigation.feedback.supplements import PersistQualifierSupplementsOperation
from marketpulse.investigation.persistence.base import create_session_factory
from marketpulse.investigation.persistence.models import AuditEventRow


@pytest.mark.parametrize("rollback", [False, True])
def test_supplements_and_audit_are_atomic(investigation_store, rollback):
    repository, engine, _ = investigation_store
    _seed_investigation(repository)
    _seed_run(repository, engine, run_id="RUN-supplement", mode=RunMode.LIVE)
    qualifiers = {"entity": {"model": "Gemini"}, "scope": {"scope": "DeepSWE"}}
    claim = Claim(
        claim_id="C-supplement",
        investigation_id=INVESTIGATION_ID,
        run_id="RUN-supplement",
        statement="Gemini scored 77.9%",
        claim_type=ClaimType.QUANTITATIVE,
        importance="HIGH",
        qualifiers=qualifiers,
        created_at=NOW,
        updated_at=NOW,
    )
    repository.add(claim)
    operation = PersistQualifierSupplementsOperation(
        claim=claim,
        supplements=(
            QualifierSupplement(
                claim_key="C1",
                evidence_key="E1",
                field="time",
                value="October 2026",
                source_quote="Results as of October 2026.",
                time_reference="RESULTS_AS_OF",
            ),
        ),
        evidence_ids={"E1": "E-real"},
        created_at=NOW,
    )
    sessions = create_session_factory(engine)
    try:
        with sessions.begin() as session:
            operation.apply(session, repository)
            if rollback:
                raise RuntimeError("later validation failed")
    except RuntimeError:
        assert rollback
    saved = repository.get(Claim, claim.claim_id)
    assert saved.qualifiers["entity"] == qualifiers["entity"]
    assert saved.qualifiers["scope"] == qualifiers["scope"]
    assert ("time" in saved.qualifiers) is not rollback
    with sessions() as session:
        audits = session.scalars(
            select(AuditEventRow).where(AuditEventRow.event_type == "CLAIM_QUALIFIERS_SUPPLEMENTED")
        ).all()
        assert len(audits) == (0 if rollback else 1)
        if audits:
            assert audits[0].metadata_payload["supplements"][0]["evidence_id"] == "E-real"
