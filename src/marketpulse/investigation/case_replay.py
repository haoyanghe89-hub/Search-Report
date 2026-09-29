"""Offline East Palestine case recording and execution replay.

The fixture provider is used only to install the bundled recording source run.
Every user-triggered run is a true ``RunMode.REPLAY`` with no live provider
fallback: recorded Search/Fetch/Model responses are consumed by
``BoundExternalCalls`` and the full Harness/Validation/Report pipeline runs
again into fresh rows.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import AnyHttpUrl, TypeAdapter
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.api import ReplayCaseOut
from marketpulse.investigation.domain.enums import (
    ReportType,
    RunMode,
    RunStatus,
    WorkflowPhase,
)
from marketpulse.investigation.domain.reports import ReportProjection
from marketpulse.investigation.domain.runtime import (
    Investigation,
    InvestigationQuestion,
    InvestigationRun,
    InvestigationScope,
    RunBudget,
)
from marketpulse.investigation.feedback.models import FeedbackLoopConfig
from marketpulse.investigation.feedback.orchestrator import AgentFeedbackOrchestrator
from marketpulse.investigation.feedback.store import FeedbackStore
from marketpulse.investigation.harness.calls import BoundExternalCalls
from marketpulse.investigation.harness.persistence import HarnessStore
from marketpulse.investigation.harness.runtime import InvestigationHarness
from marketpulse.investigation.ingestion.registry import DocumentParserRegistry
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.ports.external import (
    FetchRequest,
    FetchResult,
    ModelRequest,
    ModelUsage,
    SearchRequest,
    SearchResult,
    SearchResultItem,
    StructuredModelResult,
)
from marketpulse.investigation.recording.store import RepositoryRecordedCallStore
from marketpulse.investigation.reporting.pipeline import ReportPipeline
from marketpulse.investigation.reporting.writer import DeterministicWriter
from marketpulse.investigation.validation.integrity import EvidenceIntegrityValidator
from marketpulse.investigation.validation.models import RecognizedArtifactVersions
from marketpulse.investigation.validation.policy import ValidationPolicy

CASE_ID = "east-palestine-2023"
INVESTIGATION_ID = "INV-EAST-PALESTINE-2023"
RECORDING_RUN_ID = "RUN-EP-CURATED-RECORDING-V2"
FIXTURE_TIME = datetime(2026, 9, 28, tzinfo=UTC)  # case assembly date, not publication date
HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


@dataclass(frozen=True, slots=True)
class _FixtureSource:
    filename: str
    title: str
    url: str
    publisher: str
    source_type_hint: str
    official: bool
    first_hand: bool
    content_type: str = "text/html"


# Research articles reporting new measurements are PRIMARY/first-hand. The
# review and separately authored explanatory journalism are SECONDARY. Publisher
# diversity alone does not establish independence of a particular factual claim.
SECONDARY_SOURCES = (
    _FixtureSource(
        "pmc-hazard-review.html",
        "Known and unknown health hazards: a phased scoping review",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC12583197/",
        "Journal of Exposure Science & Environmental Epidemiology",
        "research",
        False,
        False,
    ),
    _FixtureSource(
        "chemistry-air.html",
        "Mobile mass spec provides new insight into pollutants released "
        "by East Palestine train derailment",
        "https://www.chemistryworld.com/news/mobile-mass-spec-provides-new-insight-into-pollutants-released-by-east-palestine-train-derailment/4017802.article",
        "Chemistry World",
        "media",
        False,
        False,
    ),
    _FixtureSource(
        "guardian-explainer.html",
        "What do we know about the Ohio train derailment and toxic chemical leak?",
        "https://www.theguardian.com/world/2023/feb/15/ohio-train-derailment-palestine-toxic-chemical-leak",
        "The Guardian",
        "media",
        False,
        False,
    ),
)
OFFICIAL_SOURCES = (
    _FixtureSource(
        "../ntsb_rrd23mr005_preliminary.pdf",
        "NTSB Preliminary Report RRD23MR005",
        "https://www.ntsb.gov/investigations/Documents/RRD23MR005%20East%20Palestine%20OH%20Prelim.pdf",
        "National Transportation Safety Board",
        "official",
        True,
        True,
        "application/pdf",
    ),
    _FixtureSource(
        "ntsb-investigation.html",
        "NTSB East Palestine final investigation summary",
        "https://www.ntsb.gov/investigations/Pages/RRD23MR005.aspx",
        "National Transportation Safety Board",
        "official",
        True,
        True,
    ),
    _FixtureSource(
        "epa-air.html",
        "About Air Monitoring in East Palestine",
        "https://www.epa.gov/east-palestine-oh-train-derailment/about-air-monitoring",
        "US Environmental Protection Agency",
        "official",
        True,
        True,
    ),
    _FixtureSource(
        "epa-cleanup.html",
        "Status of cleanup at the derailment site",
        "https://www.epa.gov/east-palestine-oh-train-derailment/what-status-cleanup-site",
        "US Environmental Protection Agency",
        "official",
        True,
        True,
    ),
    _FixtureSource(
        "epa-statement.html",
        "EPA regional statement on the East Palestine derailment",
        "https://www.epa.gov/newsreleases/statement-regional-administrator-debra-shore-east-palestine-train-derailment",
        "US Environmental Protection Agency",
        "official",
        True,
        True,
    ),
    _FixtureSource(
        "epa-executive-order.html",
        "Executive Order 14108 response summary",
        "https://www.epa.gov/east-palestine-oh-train-derailment/about-executive-order-14108",
        "US Environmental Protection Agency",
        "official",
        True,
        True,
    ),
    _FixtureSource(
        "pmc-air-patterns.html",
        "Air Pollutant Patterns and Human Health Risk",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC10413936/",
        "Environmental Science & Technology Letters",
        "research",
        False,
        True,
    ),
    _FixtureSource(
        "pmc-soil.html",
        "Soil contamination following the East Palestine derailment",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC11843876/",
        "Environmental Science: Processes & Impacts",
        "research",
        False,
        True,
    ),
)
# Only dates explicitly found in the original publication are populated. Unknown
# publication/retrieval dates stay unknown in the case provenance manifest.
PUBLICATION_DATES = {
    "../ntsb_rrd23mr005_preliminary.pdf": "2023-02-23",
    "epa-statement.html": "2023-02-14",
    "pmc-air-patterns.html": "2023-07-12",
    "pmc-hazard-review.html": "2025-09-12",
    "pmc-soil.html": "2025-02-18",
    "chemistry-air.html": "2023-07-31",
    "guardian-explainer.html": "2023-02-15",
}


class _FixtureSearch:
    async def search(self, request: SearchRequest) -> SearchResult:
        sources = OFFICIAL_SOURCES if "official" in request.query.casefold() else SECONDARY_SOURCES
        return SearchResult(
            items=tuple(
                SearchResultItem(
                    title=item.title,
                    url=HTTP_URL_ADAPTER.validate_python(item.url),
                    snippet="Bundled immutable replay source",
                    rank=index,
                    source_type_hint=item.source_type_hint,
                    publisher=item.publisher,
                    organization=item.publisher,
                    author=item.publisher,
                    published_at=(
                        datetime.fromisoformat(PUBLICATION_DATES[item.filename]).replace(tzinfo=UTC)
                        if item.filename in PUBLICATION_DATES
                        else None
                    ),
                    is_official=item.official,
                    is_first_hand=item.first_hand,
                    quality_metadata={
                        "data_provenance": (
                            "curated published source snapshot; "
                            "original retrieval time unknown for legacy files"
                        ),
                        "methodology": "official record"
                        if item.official
                        else "original study"
                        if item.first_hand
                        else "review or explanatory journalism",
                        "speculation_level": 0.0 if item.official else 0.1,
                        "explicit_uncertainty": True,
                    },
                )
                for index, item in enumerate(sources[: request.max_results], start=1)
            ),
            provider="east-palestine-fixture-search",
            retrieved_at=datetime.now(UTC),
        )


class _FixtureFetch:
    def __init__(self, case_root: Path) -> None:
        self._case_root = case_root.resolve()
        self._by_url = {
            item.url.rstrip("/"): item for item in (*SECONDARY_SOURCES, *OFFICIAL_SOURCES)
        }

    async def fetch(self, request: FetchRequest) -> FetchResult:
        key = str(request.url).rstrip("/")
        item = self._by_url[key]
        path = (self._case_root / "snapshots" / item.filename).resolve()
        if not path.is_relative_to(self._case_root):
            raise ValueError("fixture source path escaped case root")
        body = path.read_bytes()
        return FetchResult(
            final_url=request.url,
            status_code=200,
            content_type=item.content_type,
            body=body,
            fetched_at=datetime.now(UTC),
            headers={"x-replay-fixture": CASE_ID, "x-fetch-kind": "local-archive-materialization"},
        )


class _FixtureModel:
    """Curated regression expectations, explicitly NOT live-model recordings."""

    def __init__(self, case_root: Path) -> None:
        data = json.loads((case_root / "reviewed-pairs.json").read_text(encoding="utf-8"))
        self.pairs = data["pairs"]
        self.source_titles = {
            item.filename: item.title for item in (*SECONDARY_SOURCES, *OFFICIAL_SOURCES)
        }

    async def generate(self, request: ModelRequest[Any]) -> StructuredModelResult[Any]:
        context = json.loads(request.messages[1].content)["bounded_context"]
        name = request.response_model.__name__
        if name == "PlanProposal":
            critical_questions = [
                question for question in context["questions"] if question["is_critical"]
            ]
            payload: dict[str, Any] = {
                "tasks": [
                    {
                        "task_key": f"independent-evidence-{index}",
                        "target_question_key": question["question_key"],
                        "objective": "Find independent East Palestine derailment evidence",
                        "purpose": "Establish event facts and identify evidence gaps",
                        "priority": 100,
                        "preferred_source_types": ["TECHNICAL_ANALYSIS"],
                    }
                    for index, question in enumerate(critical_questions, start=1)
                ]
            }
        elif name == "RouteProposal":
            gaps = context["gaps"]
            target_question_key = gaps[0].get("target_question_key")
            if target_question_key is None:
                target_question_key = context["questions"][0]["question_key"]
            payload = {
                "route": "COLLECT",
                "gap_keys": [item["gap_key"] for item in gaps],
                "reason": "Collect primary official records to close the validation gaps",
                "tasks": [
                    {
                        "task_key": "official-corroboration",
                        "target_question_key": target_question_key,
                        "origin_gap_key": gaps[0]["gap_key"],
                        "target_claim_key": gaps[0].get("target_claim_key"),
                        "objective": "Find official East Palestine derailment evidence",
                        "purpose": "Add primary support and resolve source-scope differences",
                        "priority": 100,
                        "preferred_source_types": ["OFFICIAL_REPORT"],
                    }
                ],
            }
        elif name == "ResearchProposal":
            official = context["round"] == 2
            target_question_key = context["task"]["target_question_key"]
            query_key = "official-records" if official else f"independent-{target_question_key}"
            query_text = (
                "official East Palestine derailment evidence"
                if official
                else f"independent East Palestine evidence for {target_question_key}"
            )
            payload = {
                "queries": [
                    {
                        "query_key": query_key,
                        "query": query_text,
                        "target_question_key": target_question_key,
                        "purpose": (
                            "find primary official evidence"
                            if official
                            else "find independent evidence"
                        ),
                        "max_results": len(OFFICIAL_SOURCES)
                        if official
                        else len(SECONDARY_SOURCES),
                        "desired_source_role": "PRIMARY" if official else "SECONDARY",
                    }
                ]
            }
        elif name == "AnalysisProposal":
            payload = self._analysis_payload(context)
        elif name == "VerificationProposal":
            evidence = {item["evidence_key"]: item for item in context["evidence"]}
            reviewed = {
                (item["statement"], item["quote"]): item
                for item in self.pairs
                if "statement" in item
            }
            judgments = []
            scope_pair = next(item for item in self.pairs if item["key"] == "epa-air-scope")
            scope_context = next(item for item in self.pairs if item["key"] == "mobile-acrolein")
            for claim in context["claims"]:
                keys = [
                    *claim["supporting_evidence_keys"],
                    *claim.get("contradicting_evidence_keys", []),
                ]
                if claim["statement"] == scope_pair["statement"]:
                    keys.extend(
                        key
                        for key, item in evidence.items()
                        if item["quote"] == scope_context["quote"] and key not in keys
                    )
                for evidence_key in keys:
                    pair = reviewed.get((claim["statement"], evidence[evidence_key]["quote"]))
                    judgments.append(
                        {
                            "claim_key": claim["claim_key"],
                            "evidence_key": evidence_key,
                            "entailment": pair["entailment"] if pair else "NOT_RELEVANT",
                            "rationale": pair["rationale"]
                            if pair
                            else (
                                "This statement/quote pair has no reviewed support "
                                "in the curated offline case."
                            ),
                            "semantic_confidence": 0.9 if pair else 0.0,
                        }
                    )
            payload = {"judgments": judgments}
        else:
            raise AssertionError(f"unsupported fixture model contract: {name}")
        output = request.response_model.model_validate(payload)
        return StructuredModelResult(
            output=output,
            provider="curated-offline-expectations-not-live-llm",
            model="reviewed-statement-quote-allowlist-v2",
            usage=ModelUsage(input_tokens=0, output_tokens=0),
        )

    def _analysis_payload(self, context: dict[str, Any]) -> dict[str, Any]:
        evidence = []
        matched: dict[str, str] = {}
        for pair in self.pairs:
            for artifact in context["artifacts"]:
                if artifact["source_title"] != self.source_titles[pair["source_filename"]]:
                    continue
                start = artifact["excerpt"].find(pair["quote"])
                if start < 0:
                    continue
                quote_hash = hashlib.sha256(pair["quote"].encode("utf-8")).hexdigest()
                locator = dict(artifact["locator"])
                locator.update(
                    start=locator["start"] + start,
                    end=locator["start"] + start + len(pair["quote"]),
                    quote_hash=quote_hash,
                )
                key = "evidence-" + pair["key"]
                evidence.append(
                    {
                        "evidence_key": key,
                        "artifact_key": artifact["artifact_key"],
                        "quote": pair["quote"],
                        "quote_hash": quote_hash,
                        "locator": locator,
                    }
                )
                matched[pair["key"]] = key
                break
        claims = []
        timeline = []
        for pair in self.pairs:
            if "statement" not in pair:
                continue
            keys = [matched[pair["key"]]] if pair["key"] in matched else []
            qualifiers = {**pair.get("entity_qualifiers", {}), "report_section": pair["section"]}
            claims.append(
                {
                    "claim_key": pair["key"],
                    "statement": pair["statement"],
                    "canonical_statement": pair["statement"],
                    "claim_type": pair["claim_type"],
                    "importance": pair["importance"],
                    "critical": pair.get("critical", False),
                    "entity_qualifiers": qualifiers,
                    "supporting_evidence_keys": keys,
                    "atomicity": {"is_atomic": True},
                }
            )
            if keys and "event_time" in pair:
                timeline.append(
                    {
                        "timeline_key": pair["key"],
                        "description": pair["statement"],
                        "event_time": pair["event_time"],
                        "evidence_keys": keys,
                    }
                )
        observations = []
        for key, scope, definition in (
            (
                "epa-air-scope",
                "EPA community monitoring after February 8",
                "agency health-concern screening",
            ),
            (
                "mobile-acrolein",
                "mobile route sampling February 20-21",
                "concentration relative to local rural background",
            ),
        ):
            if key in matched and all(k in matched for k in ("epa-air-scope", "mobile-acrolein")):
                pair = next(item for item in self.pairs if item["key"] == key)
                observations.append(
                    {
                        "claim_key": "epa-air-scope",
                        "evidence_key": matched[key],
                        "statement": pair["statement"],
                        "conflict_type": "SCOPE",
                        "scope": scope,
                        "definition": definition,
                        "report_stage": "FINAL",
                        "directness": 0.9,
                        "specificity": 0.9,
                    }
                )
        relations = []
        if observations:
            relations.append(
                {
                    "claim_key": "epa-air-scope",
                    "evidence_key": matched["mobile-acrolein"],
                    "stance": "CONTEXT",
                }
            )
        return {
            "evidence": evidence,
            "claims": claims,
            "timeline_events": timeline,
            "relations": relations,
            "conflict_observations": observations,
        }


class EastPalestineReplayService:
    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        repository: InvestigationRepository,
        case_root: Path,
        blob_root: Path,
    ) -> None:
        self._sessions = sessions
        self._repository = repository
        self._case_root = case_root
        self._blobs = LocalContentAddressedBlobStorage(blob_root)
        self._lock = asyncio.Lock()

    async def run(self) -> ReplayCaseOut:
        return await self.run_for_investigation(INVESTIGATION_ID)

    async def run_for_investigation(self, investigation_id: str) -> ReplayCaseOut:
        """Run the bundled East Palestine replay against any investigation."""
        async with self._lock:
            self._ensure_investigation()
            await self._ensure_recording_run()
            replay_run_id = f"RUN-EP-REPLAY-{uuid.uuid4().hex[:12]}"
            self._seed_run(
                replay_run_id,
                RunMode.REPLAY,
                investigation_id=investigation_id,
                origin_run_id=RECORDING_RUN_ID,
            )
            orchestrator = self._orchestrator(
                replay_run_id,
                BoundExternalCalls(
                    sessions=self._sessions,
                    repository=self._repository,
                    recordings=RepositoryRecordedCallStore(self._repository, self._blobs),
                    source_run_id=RECORDING_RUN_ID,
                ),
            )
            outcome = await orchestrator.run(replay_run_id)
            if outcome.termination != "READY_FOR_REPORT":
                raise RuntimeError(f"East Palestine replay stopped: {outcome.reason}")
            report = await ReportPipeline(
                self._sessions, self._repository, DeterministicWriter()
            ).generate(
                run_id=replay_run_id,
                report_type=ReportType.FULL_INVESTIGATION,
                now=datetime.now(UTC),
            )
            projection = self._repository.get(ReportProjection, report.report.report_id)
            return ReplayCaseOut(
                case_id=CASE_ID,
                investigation_id=investigation_id,
                run_id=replay_run_id,
                report_id=report.report.report_id,
                run_status=outcome.termination,
                release_status=projection.release_status.value,
            )

    def _ensure_investigation(self) -> None:
        try:
            self._repository.get(Investigation, INVESTIGATION_ID)
            return
        except KeyError:
            pass
        questions = (
            "What happened, when and where?",
            "What is the sourced event timeline?",
            "What cause and contributing mechanisms did investigators identify?",
            "How were hazardous materials released and dispersed?",
            "What environmental and health impacts are observed versus unestablished?",
            "What responsibility did official investigations attribute, and with what limits?",
            "Where do official and independent accounts differ in scope or certainty?",
            "What cleanup, follow-up, and risk-management lessons are supported?",
        )
        question_models = tuple(
            InvestigationQuestion(question_id=f"EP-Q{index}", text=text, is_critical=index == 1)
            for index, text in enumerate(questions, start=1)
        )
        self._repository.add(
            Investigation(
                investigation_id=INVESTIGATION_ID,
                title="East Palestine hazardous-material train derailment",
                event_description=(
                    "The February 3, 2023 Norfolk Southern derailment, hazardous-material "
                    "release, fires, response, environmental monitoring, and remediation."
                ),
                investigation_goal=(
                    "Curated offline regression case (not a live LLM benchmark). "
                    "Reconstruct the event and distinguish verified facts, qualified findings, "
                    "source discrepancies, and remaining limitations."
                ),
                scope=InvestigationScope(
                    summary="Public official records and independent technical analyses",
                    inclusions=("cause", "timeline", "release", "impacts", "response", "lessons"),
                    geographic_scope=("East Palestine, Ohio", "nearby Pennsylvania"),
                ),
                questions=question_models,
                critical_question_ids=tuple(
                    item.question_id for item in question_models if item.is_critical
                ),
                created_at=FIXTURE_TIME,
                updated_at=FIXTURE_TIME,
            )
        )

    async def _ensure_recording_run(self) -> None:
        try:
            existing = self._repository.get(InvestigationRun, RECORDING_RUN_ID)
        except KeyError:
            existing = None
        if existing is not None:
            if existing.status is not RunStatus.READY_FOR_REPORT:
                raise RuntimeError("bundled recording source run is incomplete")
            return
        self._seed_run(RECORDING_RUN_ID, RunMode.LIVE)
        calls = BoundExternalCalls(
            sessions=self._sessions,
            repository=self._repository,
            recordings=RepositoryRecordedCallStore(self._repository, self._blobs),
            live_search=_FixtureSearch(),
            live_fetch=_FixtureFetch(self._case_root),
            live_model=_FixtureModel(self._case_root),
        )
        outcome = await self._orchestrator(RECORDING_RUN_ID, calls).run(RECORDING_RUN_ID)
        if outcome.termination != "READY_FOR_REPORT":
            raise RuntimeError(f"fixture recording source failed: {outcome.reason}")

    def _seed_run(
        self,
        run_id: str,
        mode: RunMode,
        *,
        investigation_id: str = INVESTIGATION_ID,
        origin_run_id: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        self._repository.add(
            InvestigationRun(
                run_id=run_id,
                investigation_id=investigation_id,
                mode=mode,
                status=RunStatus.CREATED,
                current_phase=WorkflowPhase.CREATED,
                checkpoint_version=0,
                state_version=0,
                workflow_version="curated-offline-v2",
                origin_run_id=origin_run_id,
                created_at=now,
                updated_at=now,
            )
        )
        HarnessStore(self._sessions, self._repository).install_budget(
            RunBudget(
                run_id=run_id,
                max_research_rounds=2,
                max_search_calls=4,
                max_fetch_calls=16,
                max_model_calls=24,
                max_tokens=80_000,
                max_wall_time_ms=180_000,
                max_sources=16,
                updated_at=now,
            )
        )

    def _orchestrator(self, run_id: str, calls: BoundExternalCalls) -> AgentFeedbackOrchestrator:
        tick = [0.0]

        def deterministic_monotonic() -> float:
            tick[0] += 0.01
            return tick[0]

        integrity = EvidenceIntegrityValidator(
            blobs=self._blobs,
            recognized_versions=RecognizedArtifactVersions(
                snapshot_parsers=frozenset(
                    {
                        ("html", "1", "text-normalizer-v1"),
                        ("plain-text", "1", "text-normalizer-v1"),
                        ("pypdf-text-layer", "1", "text-normalizer-v1"),
                    }
                ),
                artifact_processors=frozenset(
                    {("html", "1"), ("plain-text", "1"), ("pypdf-text-layer", "1")}
                ),
            ),
        )
        harness_store = HarnessStore(
            self._sessions,
            self._repository,
            clock=lambda: FIXTURE_TIME,
        )
        return AgentFeedbackOrchestrator(
            harness=InvestigationHarness(
                harness_store,
                self._blobs,
                monotonic=deterministic_monotonic,
                heartbeat_interval_seconds=60,
            ),
            calls=calls,
            store=FeedbackStore(self._sessions, self._repository),
            repository=self._repository,
            blobs=self._blobs,
            parsers=DocumentParserRegistry.default(),
            validation_policy=ValidationPolicy(integrity=integrity),
            integrity=integrity,
            owner_instance_id=f"east-palestine-{run_id}",
            config=FeedbackLoopConfig(
                workflow_version="curated-offline-v2",
                max_artifacts=20,
                max_excerpts=20,
                max_context_chars=2_000_000,
                max_verification_evidence=160,
            ),
            clock=lambda: FIXTURE_TIME,
        )


def default_case_root() -> Path:
    configured = os.getenv("EAST_PALESTINE_CASE_ROOT")
    return Path(configured) if configured else Path.cwd() / "case_data" / "east_palestine_2023"


def default_blob_root() -> Path:
    return Path(os.getenv("INVESTIGATION_BLOB_ROOT", "data/investigation-blobs"))
