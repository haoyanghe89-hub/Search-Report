from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.domain.claims import ResearchGap
from marketpulse.investigation.domain.enums import (
    AgentRole,
    ExecutionStepStatus,
    RunMode,
    RunStatus,
    StepType,
    WorkflowPhase,
)
from marketpulse.investigation.domain.runtime import (
    ExecutionStep,
    Investigation,
    InvestigationRun,
    InvestigationScope,
)
from marketpulse.investigation.domain.sources import DocumentArtifact, SourceSnapshot
from marketpulse.investigation.harness.uow import UnitOfWork
from marketpulse.investigation.ingestion.locators import make_text_locator, resolve_locator
from marketpulse.investigation.ingestion.registry import DocumentParserRegistry
from marketpulse.investigation.persistence.base import create_session_factory
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.ports.external import (
    FetchRequest,
    FetchResult,
    SearchRequest,
    SearchResult,
    SearchResultItem,
)
from marketpulse.investigation.recording.adapters import (
    CallContext,
    RecordingFetchAdapter,
    RecordingSearchAdapter,
    ReplayFetchAdapter,
    ReplaySearchAdapter,
)
from marketpulse.investigation.recording.canonical import request_fingerprint
from marketpulse.investigation.recording.store import RepositoryRecordedCallStore
from marketpulse.investigation.services.source_acquisition import (
    AcquisitionRequest,
    SourceAcquisitionService,
)

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize("material", ["pdf", "html-table"])
async def test_research_step_aggregation_persists_all_artifacts(
    investigation_store, tmp_path, material
):
    from test_phase43_feedback_loop import (
        TwoRoundModel,
        TwoRoundSearch,
        _orchestrator,
        _seed_investigation,
        _seed_run,
    )

    from marketpulse.investigation.feedback.store import FeedbackStore
    from marketpulse.investigation.harness.calls import BoundExternalCalls
    from marketpulse.investigation.ports.external import StructuredModelResult

    archive = os.getenv("TASKI_PDF_ARCHIVE")
    body = (
        await asyncio.to_thread(Path(archive).read_bytes)
        if archive
        else _pdf(
            *(
                f"Page {i}: original benchmark methodology with complete evidence."
                for i in range(1, 6)
            )
        )
    )
    if material == "html-table":
        body = _table_html()
    repository, engine, _ = investigation_store
    _seed_investigation(repository)
    run_id = "RUN-real-step-pages"
    store = _seed_run(repository, engine, run_id=run_id, mode=RunMode.LIVE, max_sources=1)
    sessions = create_session_factory(engine)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "pages")

    class MaterialOnlyModel(TwoRoundModel):
        async def generate(self, request):
            if request.response_model.__name__ == "AnalysisProposal":
                self.analysis_calls += 1
                return StructuredModelResult(
                    output=request.response_model(), provider="fixture", model="fixture"
                )
            return await super().generate(request)

    class MaterialFetch(PdfFetchFixture):
        async def fetch(self, request):
            result = await super().fetch(request)
            content_type = "text/html" if material == "html-table" else "application/pdf"
            return result.model_copy(update={"content_type": content_type})

    await _orchestrator(
        repository,
        engine,
        blobs,
        store,
        BoundExternalCalls(
            sessions=sessions,
            repository=repository,
            recordings=RepositoryRecordedCallStore(repository, blobs),
            live_search=TwoRoundSearch(),
            live_fetch=MaterialFetch(body),
            live_model=MaterialOnlyModel(),
        ),
        owner="all-pages",
    ).run(run_id)
    state = FeedbackStore(sessions, repository).state(run_id)
    assert len(state.snapshots) == 1
    if material == "pdf":
        assert sorted(a.page_number for a in state.artifacts) == [1, 2, 3, 4, 5]
        assert len({a.artifact_id for a in state.artifacts}) == 5
    else:
        assert len({a.artifact_id for a in state.artifacts}) == 2
        assert any(
            "Gemini 4 Argon: 77.9%" in blobs.get_bytes(a.blob_ref).decode() for a in state.artifacts
        )
    assert all(blobs.verify_hash(a.blob_ref) for a in state.artifacts)


def _table_html():
    return b"""<html><main><h1>Official model evaluation</h1>
    <p>A public evaluation with sufficiently detailed methodology and traceable
    original benchmark measurements, preserving units and the measured scope.</p>
    <table><caption>Agentic coding</caption><tr><th>Benchmark</th>
    <th>Gemini 4 Argon</th><th>Other model</th></tr>
    <tr><td>DeepSWE v1.1</td><td>77.9%</td><td>74.1%</td></tr></table>
    </main></html>"""


@pytest.mark.asyncio
async def test_incomplete_html_reuse_restores_table_without_refetch(investigation_store, tmp_path):
    repository, engine, _ = investigation_store
    _seed(repository, "TABLE", RunMode.LIVE)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "table")

    class Fetch(FetchFixture):
        calls = 0

        async def fetch(self, request):
            result = await super().fetch(request)
            return result.model_copy(update={"body": _table_html()})

    fetch = Fetch()
    service = SourceAcquisitionService(
        repository=repository,
        blobs=blobs,
        search=SearchFixture(),
        fetch=fetch,
        parsers=DocumentParserRegistry.default(),
        reuse_accepted_sources=True,
    )
    request = AcquisitionRequest(investigation_id="I-TABLE", run_id="RUN-TABLE", query="benchmark")
    prepared = await service.prepare(request, logical_step_key="table-intake")
    artifacts = [e for e in prepared.business_outputs if isinstance(e, DocumentArtifact)]
    assert len(artifacts) == 2
    with UnitOfWork(create_session_factory(engine), repository) as uow:
        for entity in prepared.business_outputs:
            if (
                not isinstance(entity, DocumentArtifact)
                or entity.artifact_id == artifacts[0].artifact_id
            ):
                uow.add(entity)
        uow.commit()
    repaired = await service.prepare(request, logical_step_key="table-resume")
    assert len(repaired.result.sources[0].artifact_ids) == 2
    assert fetch.calls == 1
    assert not repaired.result.sources[0].fetched
    with UnitOfWork(create_session_factory(engine), repository) as uow:
        for entity in repaired.business_outputs:
            uow.add(entity)
        uow.commit()
    assert (await service.prepare(request, logical_step_key="table-again")).business_outputs == ()
    assert len(repository.list_artifacts(prepared.result.sources[0].snapshot_id)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("official_chain", [True, False])
async def test_official_pdf_quality_requires_established_publishing_chain(
    investigation_store, tmp_path, official_chain
):
    from marketpulse.investigation.domain.sources import Source
    from marketpulse.investigation.validation.lineage import SourceLineageResolver
    from marketpulse.investigation.validation.quality import SourceQualityAssessor

    repository, _, _ = investigation_store
    _seed(repository, "CHAIN", RunMode.LIVE)
    document_url = "https://storage.googleapis.com/deepmind-media/evaluation.pdf"
    official_url = "https://deepmind.google/models/evals-methodology/evaluation"

    class Search:
        async def search(self, request):
            return SearchResult(
                items=(
                    SearchResultItem(
                        title="Model evaluation methodology",
                        url=official_url if official_chain else document_url,
                        rank=1,
                        publisher="Google DeepMind" if official_chain else None,
                        is_official=official_chain,
                        is_first_hand=official_chain,
                        source_type_hint="official" if official_chain else None,
                        quality_metadata={"publisher_family": "issuer:Google"}
                        if official_chain
                        else {},
                    ),
                ),
                provider="fixture",
                retrieved_at=NOW,
            )

    class Fetch(PdfFetchFixture):
        async def fetch(self, request):
            result = await super().fetch(request)
            return FetchResult.model_validate({**result.model_dump(), "final_url": document_url})

    result = await SourceAcquisitionService(
        repository=repository,
        blobs=LocalContentAddressedBlobStorage(tmp_path / "chain"),
        search=Search(),
        fetch=Fetch(_pdf("Complete original evaluation and traceable benchmark methodology.")),
        parsers=DocumentParserRegistry.default(),
    ).acquire(
        AcquisitionRequest(investigation_id="I-CHAIN", run_id="RUN-CHAIN", query="evaluation")
    )
    item = result.sources[0]
    source = repository.get(Source, item.source_id)
    snapshot = repository.get(SourceSnapshot, item.snapshot_id)
    family = SourceLineageResolver().resolve(sources=(source,)).families[0]
    quality = SourceQualityAssessor().assess(source=source, snapshot=snapshot, family=family)
    if official_chain:
        assert snapshot.provenance["publisher_redirect_chain"]["official_url"] == official_url
        assert snapshot.provenance["methodology"] == official_url
        assert quality.normalized_score >= 0.6
    else:
        assert "publisher_redirect_chain" not in snapshot.provenance
        assert "methodology" not in snapshot.provenance
        assert not source.is_official
        assert quality.normalized_score < 0.6


@pytest.mark.asyncio
async def test_publisher_html_link_is_archived_and_calibrates_separate_pdf_uow(
    investigation_store, tmp_path
):
    from marketpulse.investigation.domain.sources import Source
    from marketpulse.investigation.services.publisher_provenance import publisher_views

    repository, engine, _ = investigation_store
    _seed(repository, "LINK", RunMode.LIVE)
    publisher_url = "https://publisher.test/evals-methodology"
    document_url = "https://storage.googleapis.com/publisher/evaluation.pdf"

    class Search:
        async def search(self, request):
            return SearchResult(
                items=(
                    SearchResultItem(
                        title="Official methodology",
                        url=publisher_url,
                        rank=1,
                        publisher="Publisher",
                        is_official=True,
                        is_first_hand=True,
                    ),
                    SearchResultItem(title="Evaluation PDF", url=document_url, rank=2),
                ),
                provider="fixture",
                retrieved_at=NOW,
            )

    class Fetch(PdfFetchFixture):
        async def fetch(self, request):
            result = await super().fetch(request)
            if str(request.url) == publisher_url:
                return result.model_copy(
                    update={
                        "content_type": "text/html",
                        "body": (
                            "<main><h1>Evaluation methodology</h1><p>Original measurements, "
                            "protocol and results are published in the evaluation document.</p>"
                            f'<a href="{document_url}">Our evaluation PDF</a>'
                            '<a href="https://storage.googleapis.com/other/cited.pdf">'
                            'Related evaluation PDF</a></main>'
                        ).encode(),
                    }
                )
            return result

    blobs = LocalContentAddressedBlobStorage(tmp_path / "published-link")
    prepared = await SourceAcquisitionService(
        repository=repository,
        blobs=blobs,
        search=Search(),
        fetch=Fetch(_pdf("Original evaluation measurements with exact method and scope.")),
        parsers=DocumentParserRegistry.default(),
    ).prepare(
        AcquisitionRequest(investigation_id="I-LINK", run_id="RUN-LINK", query="eval"),
        logical_step_key="published-pdf",
    )
    with UnitOfWork(create_session_factory(engine), repository) as uow:
        for entity in prepared.business_outputs:
            uow.add(entity)
        uow.commit()
    sources = tuple(repository.get(Source, item.source_id) for item in prepared.result.sources)
    snapshots = tuple(
        repository.get(SourceSnapshot, item.snapshot_id) for item in prepared.result.sources
    )
    assert snapshots[0].provenance["publisher_document_links"] == [
        {
            "url": document_url,
            "anchor": "Our evaluation PDF",
            "publication_statement": "Our evaluation PDF",
        }
    ]
    effective, proven = publisher_views(sources, snapshots, blobs)
    assert effective[1].is_official and effective[1].is_first_hand
    assert proven[1].provenance["publisher_proof"]["snapshot_id"] == snapshots[0].snapshot_id
    assert proven[1].provenance["methodology"] == publisher_url
    assert not repository.get(Source, sources[1].source_id).is_official


@pytest.mark.asyncio
async def test_multipage_pdf_uow_and_incomplete_reuse(investigation_store, tmp_path):
    """Optional immutable real archive replay; always isolated from the live database."""
    archive = os.getenv("TASKI_PDF_ARCHIVE")
    body = (
        await asyncio.to_thread(Path(archive).read_bytes)
        if archive
        else _pdf(
            *(
                f"Page {i}: Gemini benchmark methodology with original evaluation evidence."
                for i in range(1, 6)
            )
        )
    )
    if archive:
        assert hashlib.sha256(body).hexdigest() == (
            "ff1df6bdeddc4c0f48840c09a8a7813b10ae7ad9e053892da68dabf64f09bff7"
        )
    repository, engine, _ = investigation_store
    _seed(repository, "MULTIPAGE", RunMode.LIVE)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "multipage")

    class Fetch(PdfFetchFixture):
        calls = 0

        async def fetch(self, request):
            self.calls += 1
            return await super().fetch(request)

    fetch = Fetch(body)
    service = SourceAcquisitionService(
        repository=repository,
        blobs=blobs,
        search=SearchFixture(),
        fetch=fetch,
        parsers=DocumentParserRegistry.default(),
        reuse_accepted_sources=True,
    )
    request = AcquisitionRequest(
        investigation_id="I-MULTIPAGE", run_id="RUN-MULTIPAGE", query="benchmark"
    )
    prepared = await service.prepare(request, logical_step_key="intake")
    pages = [e for e in prepared.business_outputs if isinstance(e, DocumentArtifact)]
    assert [p.page_number for p in pages] == [1, 2, 3, 4, 5]
    assert len({p.artifact_id for p in pages}) == 5
    # Reproduce the historical incomplete bundle, using the same UoW as Harness.
    with UnitOfWork(create_session_factory(engine), repository) as uow:
        for entity in prepared.business_outputs:
            if not isinstance(entity, DocumentArtifact) or entity.page_number == 1:
                uow.add(entity)
        uow.commit()
    snapshot_id = prepared.result.sources[0].snapshot_id
    assert len(repository.list_artifacts(snapshot_id)) == 1
    repaired = await service.prepare(request, logical_step_key="resume")
    assert len(repaired.result.sources[0].artifact_ids) == 5
    assert not repaired.result.sources[0].fetched
    assert fetch.calls == 1
    with UnitOfWork(create_session_factory(engine), repository) as uow:
        for entity in repaired.business_outputs:
            uow.add(entity)
        uow.commit()
    restored = repository.list_artifacts(snapshot_id)
    assert [p.page_number for p in restored] == [1, 2, 3, 4, 5]
    assert restored[0].artifact_id == pages[0].artifact_id
    assert all(blobs.verify_hash(p.blob_ref) for p in restored)
    assert (await service.prepare(request, logical_step_key="again")).business_outputs == ()
    print(
        {
            "archive_sha256": hashlib.sha256(body).hexdigest(),
            "persisted_pages": [p.page_number for p in restored],
            "page_chars": [len(blobs.get_bytes(p.blob_ref).decode()) for p in restored],
        }
    )


@pytest.mark.asyncio
async def test_same_run_reuses_only_accepted_persisted_snapshot(investigation_store, tmp_path):
    repository, _, _ = investigation_store
    _seed(repository, "REUSE", RunMode.LIVE)
    fetch = FetchFixture()
    service = SourceAcquisitionService(
        repository=repository,
        blobs=LocalContentAddressedBlobStorage(tmp_path / "reuse-blobs"),
        search=SearchFixture(),
        fetch=fetch,
        parsers=DocumentParserRegistry.default(),
        reuse_accepted_sources=True,
    )
    request = AcquisitionRequest(investigation_id="I-REUSE", run_id="RUN-REUSE", query="first")
    first = await service.prepare(request, logical_step_key="first")
    for entity in first.business_outputs:
        repository.add(entity)
    second = await service.prepare(
        request.model_copy(update={"query": "different query"}), logical_step_key="second"
    )
    assert fetch.calls == 1
    assert second.result.sources[0].artifact_ids == first.result.sources[0].artifact_ids
    assert second.result.sources[0].snapshot_id == first.result.sources[0].snapshot_id
    assert second.result.sources[0].evidence_eligible
    assert not second.result.sources[0].fetched
    assert second.result.valid_source_count == 0  # Not another newly collected source.
    assert second.business_outputs == ()
    assert repository.accepted_snapshot("another-run", first.result.sources[0].source_id) is None


@pytest.mark.asyncio
async def test_unreadable_snapshot_is_not_reused(investigation_store, tmp_path):
    class ShortFetch(FetchFixture):
        async def fetch(self, request):
            result = await super().fetch(request)
            return result.model_copy(update={"body": b"<html><p>empty</p></html>"})

    repository, _, _ = investigation_store
    _seed(repository, "SHORT", RunMode.LIVE)
    fetch = ShortFetch()
    service = SourceAcquisitionService(
        repository=repository,
        blobs=LocalContentAddressedBlobStorage(tmp_path / "short"),
        search=SearchFixture(),
        fetch=fetch,
        parsers=DocumentParserRegistry.default(),
        reuse_accepted_sources=True,
    )
    request = AcquisitionRequest(investigation_id="I-SHORT", run_id="RUN-SHORT", query="first")
    first = await service.prepare(request, logical_step_key="first")
    for entity in first.business_outputs:
        repository.add(entity)
    second = await service.prepare(request, logical_step_key="second")
    assert fetch.calls == 2
    assert not second.result.sources[0].evidence_eligible


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,reason",
    [
        (
            "<html><article><p>"
            + "A substantive original public record documents findings. " * 5
            + "</p></article></html>",
            "ACCEPTED",
        ),
        ("<html><p>Too short.</p></html>", "BODY_TOO_SHORT"),
        (
            "<html><title>Just a moment...</title>"
            "<form id='challenge-form'>Verify you are human</form></html>",
            "CHALLENGE_PAGE",
        ),
        ("<html><div id='root'></div><script src='/app.js'></script></html>", "JS_RENDER_REQUIRED"),
    ],
)
async def test_acquisition_retains_raw_snapshot_with_quality_diagnostics(
    investigation_store,
    tmp_path,
    caplog,
    body,
    reason,
):
    class HtmlFetch:
        async def fetch(self, request):
            return FetchResult(
                final_url=request.url,
                status_code=200,
                content_type="text/html",
                body=body.encode(),
                fetched_at=NOW,
            )

    repository, _, _ = investigation_store
    _seed(repository, "QUALITY", RunMode.LIVE)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "quality-blobs")
    service = SourceAcquisitionService(
        repository=repository,
        blobs=blobs,
        search=SearchFixture(),
        fetch=HtmlFetch(),
        parsers=DocumentParserRegistry.default(),
    )
    with caplog.at_level("INFO"):
        result = await service.acquire(
            AcquisitionRequest(
                investigation_id="I-QUALITY",
                run_id="RUN-QUALITY",
                query="official report",
                max_results=1,
            )
        )
    source = result.sources[0]
    snapshot = repository.get(SourceSnapshot, source.snapshot_id)
    diagnostics = snapshot.provenance["acquisition_diagnostics"]
    assert diagnostics["filter_reason"] == reason
    assert diagnostics["html_bytes"] == len(body.encode())
    assert diagnostics["http_status"] == 200
    assert blobs.get_bytes(snapshot.raw_blob_ref) == body.encode()
    assert reason in caplog.text
    assert result.valid_source_count == int(reason == "ACCEPTED")
    assert bool(source.artifact_ids) == (reason == "ACCEPTED")
    assert bool(source.gap_ids) == (reason != "ACCEPTED")


def _seed(repository: InvestigationRepository, suffix: str, mode: RunMode) -> None:
    repository.add(
        Investigation(
            investigation_id=f"I-{suffix}",
            title=f"Investigation {suffix}",
            event_description="A public event.",
            investigation_goal="Acquire traceable sources.",
            scope=InvestigationScope(summary="Public sources"),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        InvestigationRun(
            run_id=f"RUN-{suffix}",
            investigation_id=f"I-{suffix}",
            mode=mode,
            status=RunStatus.RUNNING,
            current_phase=WorkflowPhase.COLLECT,
            checkpoint_version=0,
            state_version=0,
            workflow_version="acquisition-v1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        ExecutionStep(
            step_id=f"STEP-{suffix}",
            run_id=f"RUN-{suffix}",
            step_type=StepType.FETCH,
            agent_role=AgentRole.HARNESS,
            status=ExecutionStepStatus.RUNNING,
            attempt=1,
            input_fingerprint=request_fingerprint(
                "search", SearchRequest(query="East Palestine official report", max_results=1)
            ),
            retryable=True,
        )
    )


class SearchFixture:
    calls = 0

    async def search(self, request: SearchRequest) -> SearchResult:
        self.calls += 1
        return SearchResult(
            items=(
                SearchResultItem(
                    title="Official incident report",
                    url="https://agency.example/report.pdf",
                    snippet="Official findings",
                    rank=1,
                    source_type_hint="official",
                ),
            ),
            provider="fixture-search",
            retrieved_at=NOW,
        )


class FetchFixture:
    calls = 0

    async def fetch(self, request: FetchRequest) -> FetchResult:
        self.calls += 1
        return FetchResult(
            final_url=request.url,
            status_code=200,
            content_type="text/html",
            body=(
                b"<html><body><h1>Finding</h1><p>The train derailed at 8:54 p.m.</p>"
                b"<p>This official record provides the original investigation findings "
                b"and documents the circumstances surrounding the public incident."
                b"</p></body></html>"
            ),
            fetched_at=NOW,
        )


class PdfFetchFixture:
    def __init__(self, body: bytes) -> None:
        self.body = body

    async def fetch(self, request: FetchRequest) -> FetchResult:
        return FetchResult(
            final_url=request.url,
            status_code=200,
            content_type="application/pdf",
            body=self.body,
            fetched_at=NOW,
        )


def _pdf(*pages: str | None) -> bytes:
    writer = PdfWriter()
    for page_text in pages:
        page = writer.add_blank_page(width=612, height=792)
        if page_text is None:
            continue
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}  # noqa: SLF001
                )
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({page_text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)  # noqa: SLF001
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _ids(prefix: str):  # type: ignore[no-untyped-def]
    counters: dict[str, int] = {}

    def factory(kind: str) -> str:
        counters[kind] = counters.get(kind, 0) + 1
        return f"{prefix}-{kind}-{counters[kind]:03d}"

    return factory


@pytest.mark.asyncio
async def test_live_then_replay_acquisition_rebuilds_snapshot_and_exact_locator(
    investigation_store: tuple[InvestigationRepository, object, str], tmp_path: Path
) -> None:
    repository, _, _ = investigation_store
    _seed(repository, "LIVE", RunMode.LIVE)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    calls = RepositoryRecordedCallStore(repository, blobs)
    live_search = SearchFixture()
    live_fetch = FetchFixture()
    search = RecordingSearchAdapter(
        live_search, calls, CallContext("RUN-LIVE", "STEP-LIVE"), clock=lambda: NOW
    )
    fetch = RecordingFetchAdapter(
        live_fetch,
        calls,
        CallContext("RUN-LIVE", "STEP-LIVE", provider="fixture-fetch"),
        clock=lambda: NOW,
    )
    service = SourceAcquisitionService(
        repository=repository,
        blobs=blobs,
        search=search,
        fetch=fetch,
        parsers=DocumentParserRegistry.default(),
        id_factory=_ids("LIVE"),
        clock=lambda: NOW,
    )
    request = AcquisitionRequest(
        investigation_id="I-LIVE",
        run_id="RUN-LIVE",
        query="East Palestine official report",
        max_results=1,
    )
    live_result = await service.acquire(request)
    live_source = live_result.sources[0]
    artifact = repository.list_artifacts(live_source.snapshot_id)[0]  # type: ignore[arg-type]
    artifact_content = blobs.get_bytes(artifact.blob_ref)
    text = artifact_content.decode()
    start = text.index("train derailed")
    locator = make_text_locator(text, start, start + len("train derailed"))

    assert live_source.valid_for_statistics is True
    assert resolve_locator(locator, artifact_content) == "train derailed"
    persisted_live = repository.get(SourceSnapshot, live_source.snapshot_id)  # type: ignore[arg-type]
    assert persisted_live.provenance["external_content_trust"] == "UNTRUSTED"
    assert (
        len(
            repository.list_replayable_tool_calls(
                run_id="RUN-LIVE",
                operation="search",
                request_fingerprint=request_fingerprint(
                    "search", SearchRequest(query=request.query, max_results=1)
                ),
            )
        )
        == 1
    )

    _seed(repository, "REPLAY", RunMode.REPLAY)
    replay_service = SourceAcquisitionService(
        repository=repository,
        blobs=blobs,
        search=ReplaySearchAdapter(calls, source_run_id="RUN-LIVE"),
        fetch=ReplayFetchAdapter(calls, source_run_id="RUN-LIVE"),
        parsers=DocumentParserRegistry.default(),
        id_factory=_ids("REPLAY"),
        clock=lambda: NOW,
    )
    replay_result = await replay_service.acquire(
        request.model_copy(update={"investigation_id": "I-REPLAY", "run_id": "RUN-REPLAY"})
    )

    assert replay_result.sources[0].valid_for_statistics is True
    assert replay_result.sources[0].snapshot_id != live_source.snapshot_id
    assert live_search.calls == 1
    assert live_fetch.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pages", "expected_status", "expected_artifact_count", "expected_valid", "gap_reason"),
    [
        ((None, None), "UNSUPPORTED_SCANNED_PDF", 0, False, "SCANNED_PDF_REQUIRES_OCR"),
        (
            ("This page has sufficient text to serve as reliable evidence in the record.", None),
            "PARTIALLY_PARSED",
            1,
            True,
            "PDF_PAGES_WITHOUT_RELIABLE_TEXT",
        ),
    ],
)
async def test_pdf_acquisition_preserves_raw_snapshot_and_only_eligible_pages(
    investigation_store: tuple[InvestigationRepository, object, str],
    tmp_path: Path,
    pages: tuple[str | None, ...],
    expected_status: str,
    expected_artifact_count: int,
    expected_valid: bool,
    gap_reason: str,
) -> None:
    repository, _, _ = investigation_store
    _seed(repository, "PDF", RunMode.LIVE)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    raw_pdf = _pdf(*pages)
    result = await SourceAcquisitionService(
        repository=repository,
        blobs=blobs,
        search=SearchFixture(),
        fetch=PdfFetchFixture(raw_pdf),
        parsers=DocumentParserRegistry.default(),
        id_factory=_ids("PDF"),
        clock=lambda: NOW,
    ).acquire(
        AcquisitionRequest(
            investigation_id="I-PDF",
            run_id="RUN-PDF",
            query="East Palestine official report",
            max_results=1,
        )
    )
    source = result.sources[0]
    assert source.snapshot_id is not None
    snapshot = repository.get(SourceSnapshot, source.snapshot_id)
    assert blobs.get_bytes(snapshot.raw_blob_ref) == raw_pdf
    assert snapshot.parse_status.value == expected_status
    assert source.valid_for_statistics is expected_valid
    assert len(repository.list_artifacts(source.snapshot_id)) == expected_artifact_count
    assert snapshot.provenance["external_content_trust"] == "UNTRUSTED"
    gap = repository.get(ResearchGap, source.gap_ids[0])
    assert gap.reason == gap_reason
