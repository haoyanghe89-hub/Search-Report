"""Read-only run inspection and public URL probes; never creates an investigation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import socket
import sqlite3
from collections import Counter
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from marketpulse.config import Settings
from marketpulse.investigation.adapters.fetch import HttpxFetchAdapter
from marketpulse.investigation.ingestion.models import DocumentParseRequest
from marketpulse.investigation.ingestion.registry import DocumentParserRegistry
from marketpulse.investigation.ports.external import FetchRequest, FetchResult

RUN_ID = "RUN-LIVE-68180c92a8cb4cb0"
SAMPLE_PATHS = (
    "https://deepmind.google/models/model-cards/gemini-3-1-pro",
    "https://deepmind.google/models/gemini/pro",
    "https://blog.google/innovation-and-ai/technology/ai/google-ai-updates-april-2026",
    "https://blog.google/innovation-and-ai/technology/ai/google-io-2026-all-our-announcements",
    "https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-4-argon",
    "https://techcrunch.com/2026/09/30/google-releases-gemini-4-argon-called-its-most-powerful-model-yet",
    "https://9to5google.com/2026/09/30/gemini-4-argon-announcement",
    "https://deepmind.google/",
    "https://blog.google/",
)
CONTROLS = (
    "https://en.wikipedia.org/wiki/Artificial_intelligence",
    "https://developers.googleblog.com/en/gemini-pro-available/",
)


def load_blob(ref: str) -> dict:
    digest = ref.rsplit("/", 1)[-1]
    body = (
        Path("data/investigation-blobs/sha256") / digest[:2] / digest[2:4] / digest
    ).read_bytes()
    if hashlib.sha256(body).hexdigest() != digest:
        raise ValueError("recording blob hash mismatch")
    return json.loads(body)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--allow-proxy-dns", action="store_true")
    parser.add_argument("--sequential", action="store_true", help="Fetch one URL at a time")
    parser.add_argument("--cached-stage", help="Reparse identical saved HTML without network calls")
    parser.add_argument(
        "--verify-ingestion",
        action="store_true",
        help="Persist captured 200 responses in an isolated probe database",
    )
    args = parser.parse_args()
    for stage in (args.stage, args.cached_stage):
        if stage is not None and not re.fullmatch(r"[a-z][a-z0-9-]*", stage):
            parser.error("stage must be a simple lowercase label, not a path")
    with sqlite3.connect("file:data/blackboard.db?mode=ro", uri=True) as connection:
        recorded = connection.execute(
            "SELECT request_blob_ref,status FROM inv_recorded_tool_calls "
            "WHERE run_id=? AND operation='fetch'",
            (RUN_ID,),
        ).fetchall()
    urls = [load_blob(ref)["request"]["url"] for ref, _ in recorded]
    selected = [(url, "run") for url in SAMPLE_PATHS if url in urls]
    selected += [(url, "control") for url in CONTROLS]
    result = {
        "run_id": RUN_ID,
        "recorded_fetches": dict(Counter(status for _, status in recorded)),
        "unique_requested_urls": len(set(urls)),
        "allow_proxy_dns": args.allow_proxy_dns,
        "started_at": datetime.now(UTC).isoformat(),
        "sequential": args.sequential,
        "dns": {
            host: sorted({value[4][0] for value in socket.getaddrinfo(host, None)})
            for host in {urlparse(url).hostname for url, _ in selected}
        },
        "probes": [],
    }
    semaphore = asyncio.Semaphore(3)
    folder = Path("reports") / "taskc-fetch" / args.stage
    folder.mkdir(parents=True, exist_ok=True)

    def save_progress(index: int, entry: dict) -> dict:
        entry["completed_at"] = datetime.now(UTC).isoformat()
        (folder / f"{index:02d}.json").write_text(
            json.dumps(entry, ensure_ascii=True, indent=2), encoding="utf-8"
        )
        result["probes"].append(entry)
        result["categories"] = dict(Counter(item["category"] for item in result["probes"]))
        (folder / "results.json").write_text(
            json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8"
        )
        print(json.dumps({"index": index, **entry}, ensure_ascii=True), flush=True)
        return entry

    (folder / "results.json").write_text(
        json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    cached_folder = (
        Path("reports") / "taskc-fetch" / args.cached_stage if args.cached_stage else None
    )
    cached = json.loads((cached_folder / "results.json").read_text()) if cached_folder else None
    traces: ContextVar[list[tuple[str, int]]] = ContextVar("fetch_probe_trace")

    async def response_hook(response: httpx.Response) -> None:
        traces.get().append((str(response.url), response.status_code))

    async with httpx.AsyncClient(event_hooks={"response": [response_hook]}) as client:
        fetch = HttpxFetchAdapter(
            client,
            allow_proxy_dns=args.allow_proxy_dns,
            user_agent=Settings().user_agent,
            max_retries=0,
        )

        async def probe(index: int, url: str, origin: str) -> dict:
            entry = {
                "url": url,
                "origin": origin,
                "http_status": None,
                "final_url": None,
                "html_bytes": None,
                "body_chars": None,
            }
            async with semaphore:
                trace: list[tuple[str, int]] = []
                token = traces.set(trace)
                try:
                    if cached_folder and cached:
                        previous = cached["probes"][index]
                        if not (cached_folder / f"{index:02d}.html").exists():
                            return save_progress(index, previous)
                        page = FetchResult(
                            final_url=previous["final_url"],
                            status_code=previous["http_status"],
                            content_type="text/html",
                            body=(cached_folder / f"{index:02d}.html").read_bytes(),
                            fetched_at="2026-10-02T00:00:00Z",
                        )
                    else:
                        async with asyncio.timeout(20):
                            page = await fetch.fetch(FetchRequest(url=url, timeout_seconds=10))
                    (folder / f"{index:02d}.html").write_bytes(page.body)
                    document = DocumentParserRegistry.default().parse(
                        DocumentParseRequest(
                            snapshot_id=f"probe-{index}",
                            url=page.final_url,
                            content=page.body,
                            declared_content_type=page.content_type,
                        )
                    )
                    entry.update(
                        http_status=page.status_code,
                        final_url=str(page.final_url),
                        html_bytes=len(page.body),
                        body_chars=len((document.normalized_content or b"").decode()),
                        eligible=document.evidence_eligible,
                        category=document.gaps[0].reason if document.gaps else "ACCEPTED",
                        warnings=document.warnings,
                        extracted_chars=next(
                            (
                                int(item.partition("=")[2])
                                for item in document.warnings
                                if item.startswith("BODY_CHARS=")
                            ),
                            len((document.normalized_content or b"").decode()),
                        ),
                    )
                except Exception as error:
                    entry.update(
                        category=getattr(error, "reason_code", None) or type(error).__name__,
                        detail=str(error)
                        if type(error).__module__.startswith("marketpulse")
                        else type(error).__name__,
                    )
                    for key in ("http_status", "html_bytes"):
                        if hasattr(error, "diagnostics"):
                            entry[key] = error.diagnostics.get(key)
                    if trace:
                        entry.update(final_url=trace[-1][0], http_status=trace[-1][1])
                finally:
                    traces.reset(token)
            return save_progress(index, entry)

        if args.sequential:
            for index, (url, origin) in enumerate(selected):
                await probe(index, url, origin)
        else:
            result["probes"] = await asyncio.gather(
                *(probe(index, url, origin) for index, (url, origin) in enumerate(selected))
            )
    result["completed_at"] = datetime.now(UTC).isoformat()
    result["categories"] = dict(Counter(entry["category"] for entry in result["probes"]))
    if args.verify_ingestion:
        result["isolated_ingestion"] = await verify_ingestion(folder, result["probes"])
    output = json.dumps(result, ensure_ascii=True, indent=2)
    (folder / "results.json").write_text(output, encoding="utf-8")
    print(output)


async def verify_ingestion(folder: Path, entries: list[dict]) -> dict:
    # This is a new local probe database, never the user's investigation database.
    from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
    from marketpulse.investigation.domain.enums import RunMode, RunStatus, WorkflowPhase
    from marketpulse.investigation.domain.runtime import (
        Investigation,
        InvestigationRun,
        InvestigationScope,
    )
    from marketpulse.investigation.persistence.base import (
        Base,
        create_investigation_engine,
        create_session_factory,
    )
    from marketpulse.investigation.persistence.repositories import InvestigationRepository
    from marketpulse.investigation.ports.external import SearchResult, SearchResultItem
    from marketpulse.investigation.services.source_acquisition import (
        AcquisitionRequest,
        SourceAcquisitionService,
    )

    pages = {
        entry["url"]: (index, entry)
        for index, entry in enumerate(entries)
        if entry["http_status"] == 200 and (folder / f"{index:02d}.html").exists()
    }
    now = datetime.now(UTC)

    class CachedSearch:
        async def search(self, request):
            return SearchResult(
                provider="offline-public-probe",
                retrieved_at=now,
                items=tuple(
                    SearchResultItem(title="Public URL probe", url=url, rank=index + 1)
                    for index, url in enumerate(pages)
                ),
            )

    class CachedFetch:
        async def fetch(self, request):
            index, entry = pages[str(request.url)]
            return FetchResult(
                final_url=entry["final_url"],
                status_code=200,
                content_type="text/html",
                body=(folder / f"{index:02d}.html").read_bytes(),
                fetched_at=now,
            )

    database = folder / "isolated-ingestion.db"
    if database.exists():
        raise ValueError("isolated ingestion database already exists; use a fresh stage label")
    engine = create_investigation_engine(f"sqlite:///{database.resolve().as_posix()}")
    try:
        Base.metadata.create_all(engine)
        repository = InvestigationRepository(create_session_factory(engine))
        repository.add(
            Investigation(
                investigation_id="I-PROBE",
                title="Offline ingestion probe",
                event_description="Read-only public responses; no factual conclusions.",
                investigation_goal="Verify source and snapshot persistence",
                scope=InvestigationScope(summary="Captured public HTML"),
                created_at=now,
                updated_at=now,
            )
        )
        repository.add(
            InvestigationRun(
                run_id="RUN-PROBE",
                investigation_id="I-PROBE",
                mode=RunMode.REPLAY,
                status=RunStatus.RUNNING,
                current_phase=WorkflowPhase.COLLECT,
                checkpoint_version=0,
                state_version=0,
                workflow_version="isolated-probe",
                created_at=now,
                updated_at=now,
            )
        )
        service = SourceAcquisitionService(
            repository=repository,
            blobs=LocalContentAddressedBlobStorage(folder / "isolated-blobs"),
            search=CachedSearch(),
            fetch=CachedFetch(),
            parsers=DocumentParserRegistry.default(),
        )
        acquired = await service.acquire(
            AcquisitionRequest(
                investigation_id="I-PROBE",
                run_id="RUN-PROBE",
                query="offline captured public pages",
                max_results=len(pages),
            )
        )
        with engine.connect() as connection:
            from sqlalchemy import text

            counts = {
                table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar()
                for table in (
                    "inv_sources",
                    "inv_source_snapshots",
                    "inv_document_artifacts",
                    "inv_research_gaps",
                    "inv_evidence",
                    "inv_claims",
                )
            }
        return {
            "database": str(database.resolve()),
            "counts": counts,
            "valid_source_count": acquired.valid_source_count,
            "model_calls": 0,
            "network_calls": 0,
        }
    finally:
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
