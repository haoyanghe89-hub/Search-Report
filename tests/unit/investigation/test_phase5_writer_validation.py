from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from marketpulse.investigation.domain.enums import (
    ClaimImportance,
    ClaimType,
    ConflictSeverity,
    ConflictStatus,
    ConflictType,
    FindingSeverity,
    ReportType,
    ValidationStatus,
)
from marketpulse.investigation.domain.reports import Report
from marketpulse.investigation.reporting.models import (
    ReportInputSemanticPayload,
    ReportInputSnapshot,
    SnapshotClaim,
    SnapshotConflict,
    SnapshotResearchGap,
)
from marketpulse.investigation.reporting.validation import ReportValidator
from marketpulse.investigation.reporting.writer import (
    COMPACT_FULL_SECTIONS,
    FULL_SECTIONS,
    STATUS_SECTIONS,
    ContentClass,
    DeterministicWriter,
    DraftSection,
    NarrativeUnit,
    ReportDraft,
    SectionStatus,
    WriterProjection,
    required_sections,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _claim(
    key: str,
    statement: str,
    status: ValidationStatus,
    claim_type: ClaimType = ClaimType.EVENT_FACT,
    critical: bool = False,
) -> SnapshotClaim:
    return SnapshotClaim(
        stable_key=key,
        semantic_hash=HASH_A,
        statement=statement,
        claim_type=claim_type,
        validation_status=status,
        confidence=0.9,
        validation_semantic_hash=HASH_B,
        importance=ClaimImportance.HIGH if critical else ClaimImportance.MEDIUM,
        is_critical=critical,
    )


def _snapshot(claims: tuple[SnapshotClaim, ...], **kwargs: object) -> ReportInputSnapshot:
    payload = ReportInputSemanticPayload(
        schema_version="phase5-report-input-v1",
        validation_policy_version="phase4-validation-v1",
        investigation_key="investigation:test",
        terminal_run_status="READY_FOR_REPORT",
        questions=("What happened?",),
        claims=claims,
        evidence=(),
        **kwargs,
    )
    return ReportInputSnapshot.build(
        snapshot_id="SNAP-1",
        investigation_id="INV-1",
        run_id="RUN-1",
        run_mode="LIVE",
        assembled_at=NOW,
        semantic_payload=payload,
    )


def _projection(snapshot: ReportInputSnapshot, report_type: ReportType) -> WriterProjection:
    return WriterProjection.build(
        snapshot,
        report_type,
        investigation_title="Test investigation",
        investigation_goal="Establish what happened.",
    )


def _report(report_type: ReportType) -> Report:
    return Report(
        report_id="R-1",
        investigation_id="INV-1",
        run_id="RUN-1",
        version=1,
        report_type=report_type,
        report_input_snapshot_hash=HASH_A,
        report_hash=HASH_B,
        claim_set_hash=HASH_C,
        citation_set_hash=HASH_A,
        release_policy_version="release-v1",
        created_at=NOW,
    )


def test_projection_excludes_trusted_material() -> None:
    snapshot = _snapshot((_claim("claim:a", "The event occurred.", ValidationStatus.VERIFIED),))
    projection = _projection(snapshot, ReportType.FULL_INVESTIGATION)
    dumped = projection.model_dump_json()
    for forbidden in ("locator", "quote_hash", "blob", "http", "sha256", "content_hash"):
        assert forbidden not in dumped.lower()
    assert projection.claims[0].stable_key == "claim:a"


def test_section_schemas() -> None:
    assert len(FULL_SECTIONS) == 17
    assert len(STATUS_SECTIONS) == 7
    assert required_sections(ReportType.FULL_INVESTIGATION) == (
        "EXECUTIVE_SUMMARY",
        "EVIDENCE_BASE",
    )
    assert required_sections(ReportType.RESTRICTED_INVESTIGATION) == (
        "EXECUTIVE_SUMMARY",
        "EVIDENCE_BASE",
    )
    assert required_sections(ReportType.INVESTIGATION_STATUS) == (
        "EXECUTIVE_STATUS",
        "EVIDENCE_BASE",
    )


async def test_deterministic_writer_full_schema_and_status_wording() -> None:
    snapshot = _snapshot(
        (
            _claim("claim:v", "The event occurred.", ValidationStatus.VERIFIED, critical=True),
            _claim("claim:p", "The cause was overheating.", ValidationStatus.PROBABLE),
            _claim("claim:d", "The valve failed first.", ValidationStatus.DISPUTED),
            _claim("claim:u", "The sensor was tampered with.", ValidationStatus.UNVERIFIED),
        )
    )
    projection = _projection(snapshot, ReportType.FULL_INVESTIGATION)
    draft = await DeterministicWriter().draft(projection)

    assert [section.section_key for section in draft.sections] == [
        key for key in COMPACT_FULL_SECTIONS if key != "TECHNICAL_APPENDIX"
    ]
    units = {unit.unit_key: unit for section in draft.sections for unit in section.units}

    probable_unit = next(u for u in units.values() if "claim:p" in u.claim_refs)
    assert any(marker in probable_unit.text.lower() for marker in ("可能", "不充分", "不确定"))
    disputed_unit = next(u for u in units.values() if "claim:d" in u.claim_refs)
    assert "争议" in disputed_unit.text
    unverified_unit = next(u for u in units.values() if "claim:u" in u.claim_refs)
    assert "尚未证实" in unverified_unit.text
    for unit in units.values():
        if unit.content_class is ContentClass.FACTUAL_ASSERTION:
            assert unit.claim_refs

    findings = ReportValidator().validate(
        draft=draft, snapshot=snapshot, citations=[], report=_report(draft.report_type), now=NOW
    )
    # Without citations every factual unit raises CITATION_INCOMPLETE; no other codes allowed.
    assert findings
    assert {finding.code for finding in findings} == {"CITATION_INCOMPLETE"}


async def test_deterministic_writer_status_report_is_compact() -> None:
    snapshot = _snapshot((_claim("claim:v", "The event occurred.", ValidationStatus.VERIFIED),))
    projection = _projection(snapshot, ReportType.INVESTIGATION_STATUS)
    draft = await DeterministicWriter().draft(projection)
    assert [section.section_key for section in draft.sections] == [
        "EXECUTIVE_STATUS",
        "EVIDENCE_BASE",
        "RESEARCH_APPENDIX",
    ]
    findings = ReportValidator().validate(
        draft=draft, snapshot=snapshot, citations=[], report=_report(draft.report_type), now=NOW
    )
    assert {finding.code for finding in findings} <= {"CITATION_INCOMPLETE"}


async def test_writer_aggregates_duplicate_gaps_and_isolates_technical_diagnostics() -> None:
    claims = (
        _claim("claim:deep", "DeepSWE 基准得分来自厂商数据。", ValidationStatus.UNVERIFIED),
        _claim("claim:vibe", "Vibe Code 基准得分来自厂商数据。", ValidationStatus.UNVERIFIED),
        _claim("claim:vals", "Vals Finance 基准得分来自厂商数据。", ValidationStatus.UNVERIFIED),
        _claim("claim:harvey", "Harvey Legal 基准得分来自厂商数据。", ValidationStatus.UNVERIFIED),
    )
    gaps = tuple(
        SnapshotResearchGap(
            stable_key=f"gap:{index}",
            gap_type="INSUFFICIENT_INDEPENDENCE",
            severity="HIGH",
            status="OPEN",
            reason="至少两个质量充分的支持来源",
            target_claim_stable_key=claim.stable_key,
        )
        for index, claim in enumerate(claims)
    ) + (
        SnapshotResearchGap(
            stable_key="gap:pdf",
            gap_type="UNREADABLE_SOURCE",
            severity="MEDIUM",
            status="OPEN",
            reason="PDF_IMAGE_CONTENT_NOT_EXTRACTED",
            suggested_actions=("Pages contain images; use OCR before citing image cells.",),
        ),
    )
    snapshot = _snapshot(
        claims,
        research_gaps=gaps,
        limitations=(
            "至少两个质量充分的支持来源",
            "PDF_IMAGE_CONTENT_NOT_EXTRACTED",
            "search.q2:SearchUnavailableError",
            "Profile requirement is not met: an exact ENTAILS judgment is required",
        ),
    )

    draft = await DeterministicWriter().draft(
        _projection(snapshot, ReportType.INVESTIGATION_STATUS)
    )
    sections = {section.section_key: section for section in draft.sections}

    assert "EXECUTIVE_STATUS" in sections
    assert "AVAILABLE_FINDINGS" not in sections
    assert "NEXT_STEPS" not in sections
    assert all(section.units for section in draft.sections)
    body = "\n".join(
        unit.text
        for section in draft.sections
        if section.section_key != "TECHNICAL_APPENDIX"
        for unit in section.units
    )
    appendix = "\n".join(
        unit.text for unit in sections["TECHNICAL_APPENDIX"].units
    )
    assert "SearchUnavailableError" not in body
    assert "PDF_IMAGE_CONTENT_NOT_EXTRACTED" not in body
    assert "Profile requirement is not met" not in body
    assert "SearchUnavailableError" in appendix
    assert body.count("至少两个质量充分的支持来源") == 1
    assert body.count("后续建议") == 2
    assert "相关来源当前缺少可读取的文本内容" in body
    for benchmark in ("DeepSWE", "Vibe Code", "Vals Finance", "Harvey Legal"):
        assert body.count(benchmark) == 1


async def test_chinese_report_preserves_claims_and_uncertainty_without_numeric_confidence() -> None:
    snapshot = _snapshot(
        (
            _claim("claim:v", "机构记录了该事件。", ValidationStatus.VERIFIED, ClaimType.STATEMENT),
            _claim("claim:u", "尚待核实的原因。", ValidationStatus.UNVERIFIED, critical=True),
        )
    )
    before = snapshot.model_dump_json()
    draft = await DeterministicWriter().draft(
        _projection(snapshot, ReportType.INVESTIGATION_STATUS)
    )
    assert snapshot.model_dump_json() == before
    units = [u for section in draft.sections for u in section.units]
    unverified = next(u for u in units if "claim:u" in u.claim_refs)
    assert "尚不能确认" in unverified.text
    assert unverified.content_class is ContentClass.GOVERNANCE_DISCLOSURE
    assert not any("0.9" in u.text or "90%" in u.text for u in units)
    assert draft.schema_version == "report-writer-zh-v4"


async def test_writer_v4_probable_is_answer_first_without_claiming_verified() -> None:
    snapshot = _snapshot(
        (
            _claim("claim:p", "该结果在已记录范围内很可能成立。", ValidationStatus.PROBABLE),
            _claim("claim:u", "尚待核实的外推结论。", ValidationStatus.UNVERIFIED),
        )
    )
    before = snapshot.model_dump_json()
    draft = await DeterministicWriter().draft(_projection(snapshot, ReportType.FULL_INVESTIGATION))
    assert draft.schema_version == "report-writer-zh-v4"
    assert snapshot.model_dump_json() == before
    summary = next(
        section for section in draft.sections if section.section_key == "EXECUTIVE_SUMMARY"
    )
    finding = next(unit for unit in summary.units if "claim:p" in unit.claim_refs)
    assert finding.content_class is ContentClass.FACTUAL_ASSERTION
    assert "很可能成立" in finding.text
    assert "不等同于已验证" in finding.text
    assert not any("尚无通过验证的关键发现" in unit.text for unit in summary.units)
    unresolved = next(unit for unit in summary.units if "claim:u" in unit.claim_refs)
    assert "尚不能确认" in unresolved.text
    findings = ReportValidator().validate(
        draft=draft, snapshot=snapshot, citations=[], report=_report(draft.report_type), now=NOW
    )
    assert any(item.code == "CITATION_INCOMPLETE" for item in findings)


def test_reviewed_chinese_translation_preserves_limit_and_catalogs_match() -> None:
    import json
    from pathlib import Path

    from marketpulse.investigation.agents.prompts import COMMON_BOUNDARY
    from marketpulse.investigation.localization import chinese_text

    root = Path(__file__).resolve().parents[3]
    server = json.loads(
        (root / "src/marketpulse/investigation/zh_CN.json").read_text(encoding="utf-8")
    )
    browser = json.loads((root / "frontend/src/locales/zh-CN.json").read_text(encoding="utf-8"))
    assert server == browser
    statement = next(text for text in server["texts"] if "not a sixfold exceedance" in text)
    assert "不等于超过健康限值六倍" in chinese_text(statement)
    assert chinese_text("An unknown archived statement.") == "An unknown archived statement."
    assert "Simplified Chinese" in COMMON_BOUNDARY
    assert "verbatim evidence quotes unchanged" in COMMON_BOUNDARY


def _draft_with_unit(unit: NarrativeUnit, claim_keys: tuple[str, ...]) -> ReportDraft:
    sections = [
        DraftSection(section_key=key, status=SectionStatus.NOT_APPLICABLE)
        for key in FULL_SECTIONS
        if key != "VERIFIED_FINDINGS"
    ]
    sections.append(
        DraftSection(
            section_key="VERIFIED_FINDINGS",
            status=SectionStatus.CONTENT,
            units=(unit,),
        )
    )
    return ReportDraft(report_type=ReportType.FULL_INVESTIGATION, sections=tuple(sections))


def test_validator_flags_factual_unit_without_claims() -> None:
    snapshot = _snapshot((_claim("claim:v", "The event occurred.", ValidationStatus.VERIFIED),))
    unit = NarrativeUnit(
        unit_key="u-1",
        section_key="VERIFIED_FINDINGS",
        text="Something unsupported happened.",
        content_class=ContentClass.FACTUAL_ASSERTION,
    )
    draft = _draft_with_unit(unit, ())
    findings = ReportValidator().validate(
        draft=draft, snapshot=snapshot, citations=[], report=_report(draft.report_type), now=NOW
    )
    codes = {finding.code for finding in findings}
    assert "UNSUPPORTED_REPORT_CONTENT" in codes
    assert all(finding.severity is FindingSeverity.HARD for finding in findings)


def test_validator_flags_qualifier_loss_for_probable() -> None:
    snapshot = _snapshot((_claim("claim:p", "The tank overheated.", ValidationStatus.PROBABLE),))
    unit = NarrativeUnit(
        unit_key="u-1",
        section_key="VERIFIED_FINDINGS",
        text="The tank overheated.",
        content_class=ContentClass.FACTUAL_ASSERTION,
        claim_refs=("claim:p",),
    )
    draft = _draft_with_unit(unit, ("claim:p",))
    findings = ReportValidator().validate(
        draft=draft, snapshot=snapshot, citations=[], report=_report(draft.report_type), now=NOW
    )
    assert "QUALIFIER_LOSS" in {finding.code for finding in findings}


def test_validator_flags_unknown_claim_ref() -> None:
    snapshot = _snapshot((_claim("claim:v", "The event occurred.", ValidationStatus.VERIFIED),))
    unit = NarrativeUnit(
        unit_key="u-1",
        section_key="VERIFIED_FINDINGS",
        text="The event occurred.",
        content_class=ContentClass.FACTUAL_ASSERTION,
        claim_refs=("claim:ghost",),
    )
    draft = _draft_with_unit(unit, ())
    findings = ReportValidator().validate(
        draft=draft, snapshot=snapshot, citations=[], report=_report(draft.report_type), now=NOW
    )
    assert "UNSUPPORTED_REPORT_CONTENT" in {finding.code for finding in findings}


def test_validator_flags_critical_claim_omission() -> None:
    snapshot = _snapshot(
        (
            _claim("claim:v", "The event occurred.", ValidationStatus.VERIFIED, critical=True),
            _claim("claim:x", "Extra detail.", ValidationStatus.VERIFIED),
        )
    )
    unit = NarrativeUnit(
        unit_key="u-1",
        section_key="VERIFIED_FINDINGS",
        text="Extra detail.",
        content_class=ContentClass.FACTUAL_ASSERTION,
        claim_refs=("claim:x",),
    )
    draft = _draft_with_unit(unit, ("claim:x",))
    findings = ReportValidator().validate(
        draft=draft, snapshot=snapshot, citations=[], report=_report(draft.report_type), now=NOW
    )
    assert "CRITICAL_CLAIM_OMITTED" in {finding.code for finding in findings}


def test_validator_flags_missing_section() -> None:
    snapshot = _snapshot((_claim("claim:v", "The event occurred.", ValidationStatus.VERIFIED),))
    draft = ReportDraft(
        report_type=ReportType.FULL_INVESTIGATION,
        sections=(
            DraftSection(
                section_key="VERIFIED_FINDINGS",
                status=SectionStatus.CONTENT,
                units=(
                    NarrativeUnit(
                        unit_key="u-1",
                        section_key="VERIFIED_FINDINGS",
                        text="The event occurred.",
                        content_class=ContentClass.FACTUAL_ASSERTION,
                        claim_refs=("claim:v",),
                    ),
                ),
            ),
        ),
    )
    findings = ReportValidator().validate(
        draft=draft, snapshot=snapshot, citations=[], report=_report(draft.report_type), now=NOW
    )
    assert "SCHEMA_SECTION_MISSING" in {finding.code for finding in findings}


def test_unresolved_conflict_must_be_surfaced() -> None:
    claim = _claim("claim:v", "The event occurred.", ValidationStatus.VERIFIED, critical=True)
    snapshot = _snapshot(
        (claim,),
        conflicts=(
            SnapshotConflict(
                stable_key="conflict:c",
                conflict_type=ConflictType.QUANTITATIVE,
                severity=ConflictSeverity.MEDIUM,
                status=ConflictStatus.OPEN,
                claim_stable_keys=("claim:v",),
                semantic_hash=HASH_C,
            ),
        ),
    )
    projection = _projection(snapshot, ReportType.FULL_INVESTIGATION)
    draft = asyncio.run(DeterministicWriter().draft(projection))
    findings = ReportValidator().validate(
        draft=draft, snapshot=snapshot, citations=[], report=_report(draft.report_type), now=NOW
    )
    codes = {finding.code for finding in findings}
    # Deterministic writer surfaces conflicts in CONFLICT_ANALYSIS with claim refs.
    assert "CRITICAL_CONFLICT_OMITTED" not in codes


def test_open_gap_must_be_disclosed() -> None:
    snapshot = _snapshot(
        (_claim("claim:v", "The event occurred.", ValidationStatus.VERIFIED, critical=True),),
        research_gaps=(
            SnapshotResearchGap(
                stable_key="gap:g",
                gap_type="EVIDENCE_GAP",
                severity="HIGH",
                status="OPEN",
                reason="Missing primary record.",
            ),
        ),
    )
    sections = [
        DraftSection(section_key=key, status=SectionStatus.NOT_APPLICABLE)
        for key in FULL_SECTIONS
        if key not in ("VERIFIED_FINDINGS", "LIMITATIONS_AND_RESEARCH_GAPS")
    ]
    sections.append(
        DraftSection(
            section_key="VERIFIED_FINDINGS",
            status=SectionStatus.CONTENT,
            units=(
                NarrativeUnit(
                    unit_key="u-1",
                    section_key="VERIFIED_FINDINGS",
                    text="The event occurred.",
                    content_class=ContentClass.FACTUAL_ASSERTION,
                    claim_refs=("claim:v",),
                ),
            ),
        )
    )
    sections.append(
        DraftSection(section_key="LIMITATIONS_AND_RESEARCH_GAPS", status=SectionStatus.CONTENT)
    )
    draft = ReportDraft(report_type=ReportType.FULL_INVESTIGATION, sections=tuple(sections))
    findings = ReportValidator().validate(
        draft=draft, snapshot=snapshot, citations=[], report=_report(draft.report_type), now=NOW
    )
    codes = {finding.code for finding in findings}
    assert "OPEN_GAP_NOT_DISCLOSED" in codes


def test_resolved_gap_does_not_require_open_gap_disclosure() -> None:
    snapshot = _snapshot(
        (_claim("claim:v", "The event occurred.", ValidationStatus.VERIFIED),),
        research_gaps=(
            SnapshotResearchGap(
                stable_key="gap:resolved",
                gap_type="EVIDENCE_GAP",
                severity="HIGH",
                status="RESOLVED",
                reason="Primary record was acquired.",
            ),
        ),
    )
    draft = asyncio.run(
        DeterministicWriter().draft(_projection(snapshot, ReportType.FULL_INVESTIGATION))
    )

    findings = ReportValidator().validate(
        draft=draft,
        snapshot=snapshot,
        citations=[],
        report=_report(draft.report_type),
        now=NOW,
    )

    assert "OPEN_GAP_NOT_DISCLOSED" not in {finding.code for finding in findings}
