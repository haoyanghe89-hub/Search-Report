from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from marketpulse.adapters.fetch import PageFetcher
from marketpulse.adapters.robots import RobotsPolicy
from marketpulse.adapters.search import PublicSearchClient
from marketpulse.agents.factory import DeepSeekAgentRunner
from marketpulse.budget import RunBudget
from marketpulse.config import Settings
from marketpulse.domain.analysis import MarketAnalysis, QualityResult
from marketpulse.domain.collaboration import BlackboardEvent, BlackboardState
from marketpulse.domain.evidence import CoverageSummary, Source
from marketpulse.errors import ErrorCode, MarketPulseError
from marketpulse.observability import RunLogger, RunStats
from marketpulse.services.blackboard import BlackboardStore
from marketpulse.workflow import (
    MarketPulseRequest,
    MarketPulseResult,
    WorkflowDependencies,
    run_marketpulse,
)
from marketpulse.investigation.api import router as investigation_router
from marketpulse.investigation.review.api import router as review_router
from marketpulse.investigation.persistence.base import (
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.persistence.models import (
    InvestigationQuestionRow,
    InvestigationRow,
)
from fastapi.staticfiles import StaticFiles


class ReportRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    competitor_limit: int = Field(default=5, ge=3, le=8)


class ReportResponse(BaseModel):
    run_id: str
    topic: str
    generated_at: datetime
    report_path: str
    analysis: MarketAnalysis
    coverage: CoverageSummary
    sources: list[Source]
    quality: QualityResult
    stats: dict[str, object]
    warnings: list[str]
    report_markdown: str
    agent_events: list[BlackboardEvent] = Field(default_factory=list)
    state_version: int = 0
    storage_backend: str = "sqlite"


app = FastAPI(title="MarketPulse API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-Requested-With"],
)

# --- Investigation API integration ---
_inv_settings = Settings.from_env(require_api_key=False)
_inv_db_url = _inv_settings.database_url.get_secret_value()
_inv_engine = create_investigation_engine(_inv_db_url)
_inv_sessions = create_session_factory(_inv_engine)
_inv_repository = InvestigationRepository(_inv_sessions)
app.state.inv_engine = _inv_engine
app.state.inv_sessions = _inv_sessions
app.state.inv_repository = _inv_repository
app.state.review_session_factory = _inv_sessions
app.state.settings = _inv_settings
# Configure East Palestine replay runner
from marketpulse.investigation.case_replay import (
    EastPalestineReplayService,
    default_blob_root,
    default_case_root,
)
app.state.east_palestine_replay = EastPalestineReplayService(
    sessions=_inv_sessions,
    repository=_inv_repository,
    case_root=default_case_root(),
    blob_root=default_blob_root(),
)
# include_router has compatibility issues with this FastAPI version; add routes directly
for _route in investigation_router.routes:
    app.router.routes.append(_route)
for _route in review_router.routes:
    app.router.routes.append(_route)

# --- Frontend static files ---
if os.getenv("INVESTIGATION_SERVE_FRONTEND", "false").lower() in {"1", "true", "yes"}:
    from fastapi.responses import FileResponse
    _frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    if _frontend_dir.is_dir():
        @app.get("/")
        def _serve_index() -> FileResponse:
            return FileResponse(str(_frontend_dir / "index.html"))
        @app.get("/app.js")
        def _serve_app_js() -> FileResponse:
            return FileResponse(str(_frontend_dir / "app.js"))
        @app.get("/styles.css")
        def _serve_styles() -> FileResponse:
            return FileResponse(str(_frontend_dir / "styles.css"))

# Keep local API workload bounded; model clients are now scoped to each run.
_run_lock = asyncio.Lock()


def _slug(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text).strip("-").lower()
    return value[:50] or "market"


def _report_path(topic: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    root = Path(os.getenv("MARKETPULSE_REPORT_DIR", "reports"))
    return root / f"{_slug(topic)}-{stamp}.md"


async def _run_topic(payload: ReportRequest, run_id: str | None = None) -> MarketPulseResult:
    settings = Settings.from_env()
    stats = RunStats(run_id=run_id) if run_id else RunStats()
    logger = RunLogger(stats.run_id)
    budget = RunBudget.start(settings)
    runner = DeepSeekAgentRunner(settings)
    try:
        async with httpx.AsyncClient(max_redirects=5) as http_client:
            robots = RobotsPolicy(http_client, settings)
            dependencies = WorkflowDependencies(
                search=PublicSearchClient(http_client, settings, budget),
                fetcher=PageFetcher(http_client, settings, budget, robots),
                runner=runner,
                budget=budget,
                logger=logger,
            )
            return await run_marketpulse(
                MarketPulseRequest(
                    topic=payload.topic,
                    competitor_limit=payload.competitor_limit,
                    output_path=_report_path(payload.topic),
                ),
                dependencies,
                settings,
            )
    finally:
        await runner.aclose()


@app.exception_handler(MarketPulseError)
async def marketpulse_error_handler(_: Request, exc: MarketPulseError) -> JSONResponse:
    status_by_code = {
        ErrorCode.INVALID_INPUT: 422,
        ErrorCode.CONFIG_ERROR: 503,
        ErrorCode.SEARCH_UNAVAILABLE: 502,
        ErrorCode.NO_USABLE_EVIDENCE: 422,
        ErrorCode.TIMEOUT: 504,
        ErrorCode.OUTPUT_WRITE_FAILED: 500,
        ErrorCode.INTERNAL_ERROR: 500,
    }
    logging.getLogger("marketpulse").warning(
        "API run failed: code=%s message=%s",
        int(exc.code),
        str(exc),
    )
    return JSONResponse(
        status_code=status_by_code.get(exc.code, 500),
        content={"detail": str(exc), "code": int(exc.code)},
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "marketpulse"}


@app.get("/api/runs/{run_id}", response_model=BlackboardState)
def read_run(run_id: str) -> BlackboardState:
    settings = Settings.from_env(require_api_key=False)
    board = BlackboardStore(settings.database_url.get_secret_value())
    try:
        return board.load(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    finally:
        board.close()


@app.get("/api/runs/{run_id}/events", response_model=list[BlackboardEvent])
def read_run_events(run_id: str, after_version: int = -1) -> list[BlackboardEvent]:
    settings = Settings.from_env(require_api_key=False)
    board = BlackboardStore(settings.database_url.get_secret_value())
    try:
        board.load(run_id)
        return board.history(run_id, after_version=after_version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    finally:
        board.close()


@app.post("/api/reports", response_model=ReportResponse)
async def create_report(payload: ReportRequest) -> ReportResponse:
    async with _run_lock:
        result = await _run_topic(payload)
    return ReportResponse(
        run_id=result.run_id,
        topic=payload.topic.strip(),
        generated_at=datetime.now(UTC),
        report_path=str(result.report_path),
        analysis=result.analysis,
        coverage=result.coverage,
        sources=result.evidence.sources,
        quality=result.quality,
        stats=asdict(result.stats),
        warnings=[*result.evidence.warnings, *result.stats.warnings],
        report_markdown=result.report_markdown,
        agent_events=result.agent_events,
        state_version=result.state_version,
        storage_backend=result.storage_backend,
    )


# --- Async live research (background task + polling) ---
_live_tasks: dict[str, asyncio.Task] = {}


class LiveResearchStartOut(BaseModel):
    run_id: str
    status: str = "running"


@app.post(
    "/api/investigations/{investigation_id}/research",
    response_model=LiveResearchStartOut,
    status_code=202,
)
async def start_live_research(investigation_id: str, request: Request) -> LiveResearchStartOut:
    sessions = request.app.state.inv_sessions
    with sessions() as session:
        row = session.get(InvestigationRow, investigation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="调查不存在")
        topic = row.title if not row.investigation_goal else f"{row.title}：{row.investigation_goal}"
    run_id = f"run_{uuid.uuid4().hex[:12]}"

    async def _job() -> None:
        try:
            await _run_topic(ReportRequest(topic=topic[:200]), run_id=run_id)
        except Exception:
            logging.getLogger("marketpulse").exception("live research failed: %s", run_id)

    _live_tasks[run_id] = asyncio.create_task(_job())
    return LiveResearchStartOut(run_id=run_id)


@app.get("/api/live-runs/{run_id}")
def read_live_run(run_id: str) -> dict:
    settings = Settings.from_env(require_api_key=False)
    board = BlackboardStore(settings.database_url.get_secret_value())
    try:
        state = board.load(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="运行尚未就绪或不存在") from exc
    finally:
        board.close()
    return state.model_dump(mode="json")


class InvestigationUpdateIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    event_description: str = Field(min_length=1)
    investigation_goal: str = Field(min_length=1)
    questions: list[str] = Field(default_factory=list)


@app.patch("/api/investigations/{investigation_id}")
def update_investigation(
    investigation_id: str, payload: InvestigationUpdateIn, request: Request
) -> dict:
    sessions = request.app.state.inv_sessions
    now = datetime.now(UTC)
    with sessions() as session:
        row = session.get(InvestigationRow, investigation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="调查不存在")
        row.title = payload.title.strip()
        row.event_description = payload.event_description
        row.investigation_goal = payload.investigation_goal
        row.scope = {"summary": payload.event_description}
        row.updated_at = now
        session.query(InvestigationQuestionRow).filter_by(
            investigation_id=investigation_id
        ).delete()
        for text in payload.questions:
            if text.strip():
                session.add(
                    InvestigationQuestionRow(
                        question_id=f"Q-{uuid.uuid4().hex}",
                        investigation_id=investigation_id,
                        text=text.strip(),
                        is_critical=False,
                    )
                )
        session.commit()
    return {"investigation_id": investigation_id, "updated_at": now.isoformat()}


def main() -> None:
    logging.basicConfig(level=os.getenv("MARKETPULSE_LOG_LEVEL", "INFO").upper())
    uvicorn.run(
        "marketpulse.web_api:app",
        host="127.0.0.1",
        port=int(os.getenv("MARKETPULSE_API_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
