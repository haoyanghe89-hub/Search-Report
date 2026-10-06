"""Additive local-operator API; never exports raw provider datasets."""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import select

from marketpulse.investigation.api import (
    InvestigationCreateIn,
    _error,
    _get_run_row,
    _run_out,
    _sessions,
    create_investigation,
)
from marketpulse.investigation.depth import depth_settings
from marketpulse.investigation.domain.enums import RunMode, RunStatus, WorkflowPhase
from marketpulse.investigation.domain.runtime import InvestigationRun, RunBudget
from marketpulse.investigation.persistence.models import InvestigationRunRow, ReportRow

from .domain import FrozenModel, Instrument
from .storage.models import InstrumentRow

router = APIRouter(prefix="/api/quant", tags=["quant"])
DEPENDENCIES = ("numpy", "pandas", "pyarrow", "duckdb", "akshare", "baostock", "exchange_calendars")


def missing_dependencies():
    return [name for name in DEPENDENCIES if importlib.util.find_spec(name) is None]


class QuantRunIn(FrozenModel):
    instrument: str = Field(min_length=1, max_length=100)
    date_start: date | None = None
    date_end: date | None = None
    window: Literal["1y", "3y"] = "1y"
    adjustment: Literal["raw", "qfq", "hfq"] = "raw"
    depth: Literal["quick", "standard", "deep"] = "standard"
    asof: AwareDatetime | None = None
    benchmark: str | None = None
    rf: str | Literal["zero"] | None = None
    frozen_snapshot_ids: tuple[str, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def bounds(self):
        if (self.date_start is None) != (self.date_end is None):
            raise ValueError("date_start/date_end must be supplied together")
        if self.date_start and (
            self.date_end < self.date_start or (self.date_end - self.date_start).days > 1096
        ):
            raise ValueError("ordered range <=3 years required")
        return self


def _runtime(request):
    runtime = getattr(request.app.state, "quant_runtime", None)
    if runtime is None:
        raise _error(
            503,
            "QUANT_NOT_CONFIGURED",
            "量化依赖不可用；网页调查仍可使用。请安装 quant extra 并重启。",
        )
    return runtime


def instruments(sessions, q="", limit=20):
    with sessions() as session:
        definitions = session.scalars(
            select(InstrumentRow.definition).order_by(InstrumentRow.instrument_id)
        ).all()
    result = []
    for definition in definitions:
        item = Instrument.model_validate(definition)
        alias = item.aliases[-1]
        if q.casefold() not in (item.name + alias.code + item.instrument_id).casefold():
            continue
        result.append(
            dict(
                instrument_id=item.instrument_id,
                code=alias.code,
                name=item.name,
                market=item.market,
                exchange=alias.exchange,
                board=item.board,
                status="delisted" if item.delisted_at else "listed",
            )
        )
        if len(result) >= limit:
            break
    return result


@router.get("/instruments")
def search_instruments(
    request: Request, q: str = Query("", max_length=100), limit: int = Query(20, ge=1, le=100)
):
    _runtime(request)
    return instruments(_sessions(request), q, limit)


@router.post("/runs", status_code=202)
async def start_run(payload: QuantRunIn, request: Request):
    runtime = _runtime(request)
    matches = [
        i
        for i in await asyncio.to_thread(
            instruments, runtime.service.sessions, payload.instrument, 100
        )
        if payload.instrument in (i["instrument_id"], i["code"])
    ]
    if len(matches) != 1:
        raise _error(
            422,
            "QUANT_INSTRUMENT_UNKNOWN",
            "标的未主数据化或代码有歧义，请从证券搜索选择 ins_ ID。",
        )
    asof = payload.asof or datetime.now(UTC)
    if asof > datetime.now(UTC):
        raise _error(422, "QUANT_FUTURE_ASOF", "研究时点不能在未来。")
    cutoff = asof.astimezone(ZoneInfo("Asia/Shanghai")).date()
    end = payload.date_end or cutoff - timedelta(days=1)
    start = payload.date_start or end - timedelta(days=365 if payload.window == "1y" else 1095)
    if end >= cutoff:
        raise _error(
            422,
            "QUANT_INCOMPLETE_SESSION",
            "P0 仅使用已完整收盘的历史交易日；结束日须早于研究时点日期。",
        )
    if payload.benchmark or (payload.rf and payload.rf != "zero"):
        raise _error(
            422,
            "QUANT_REFERENCE_UNAVAILABLE",
            "P0 尚无标准化基准/利率快照契约；不能用代码或文本代替冻结输入。",
        )
    plan = payload.model_copy(
        update={
            "instrument": matches[0]["instrument_id"],
            "asof": asof,
            "date_start": start,
            "date_end": end,
        }
    )
    try:
        if plan.frozen_snapshot_ids:
            await asyncio.to_thread(runtime.validate_pins, plan)
    except (ValueError, KeyError) as error:
        raise _error(
            422, "QUANT_FROZEN_INPUT_INVALID", "冻结输入不匹配、存在歧义或完整性校验失败。"
        ) from error
    archive = await asyncio.to_thread(
        create_investigation,
        InvestigationCreateIn(
            title=f"{matches[0]['name']} · 量化投研",
            event_description=f"冻结区间 {start} 至 {end}",
            investigation_goal="核对收益、风险与同口径估值；不做投资建议或预测。",
            questions=["冻结数据可确认什么，哪些结论仍未验证？"],
            depth=plan.depth,
        ),
        request,
    )
    run_id = runtime.start(archive.investigation_id, plan)
    return dict(run_id=run_id, investigation_id=archive.investigation_id, status="CREATED")


@router.get("/instruments/{instrument_id}/windows")
def frozen_windows(instrument_id: str, request: Request):
    from .windows import available_windows

    runtime = _runtime(request)
    return available_windows(runtime.service, instrument_id)


@router.get("/runs")
def list_runs(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: RunStatus | None = None,
):
    _runtime(request)
    with _sessions(request)() as session:
        query = select(InvestigationRunRow).where(
            InvestigationRunRow.workflow_version == "quant-v1"
        )
        if status:
            query = query.where(InvestigationRunRow.status == status)
        return [
            _run_out(r)
            for r in session.scalars(
                query.order_by(InvestigationRunRow.created_at.desc()).offset(offset).limit(limit)
            )
        ]


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    runtime = _runtime(request)
    with _sessions(request)() as session:
        row = _get_run_row(session, run_id)
        if row.workflow_version != "quant-v1":
            raise _error(404, "RUN_NOT_FOUND", "量化运行不存在。")
        report = session.scalar(
            select(ReportRow)
            .where(ReportRow.run_id == run_id)
            .order_by(ReportRow.created_at.desc())
        )
        result = dict(
            schema_version="quant-v1",
            run=_run_out(row),
            phase=runtime.phase(run_id, row),
            report_id=report.report_id if report else None,
            values=[],
            charts=[],
            gaps=[],
            evidence_count=0,
            citation_count=0,
        )
    try:
        result.update(runtime.presentation(run_id))
    except (ValueError, KeyError, PermissionError) as error:
        raise _error(
            409, "QUANT_INTEGRITY_FAILED", "计算产物或最新验证链发生漂移，数值已停止展示。"
        ) from error
    return result


class PublicQuantRuntime:
    def __init__(self, service, runner, journal_root):
        self.service, self.runner, self.journal_root = service, runner, journal_root
        self.phases = {}
        service.public_phase = self.set_phase

    def set_phase(self, run_id, name, phase):
        self.phases[run_id] = name
        with self.service.sessions.begin() as session:
            row = session.get(InvestigationRunRow, run_id)
            row.current_phase = phase
            row.state_version += 1
            row.updated_at = datetime.now(UTC)

    def phase(self, run_id, row):
        return self.phases.get(run_id) or (
            "成稿"
            if row.status == RunStatus.COMPLETED
            else "证据核验"
            if row.current_phase == WorkflowPhase.VERIFY
            else "确定性计算"
        )

    def validate_pins(self, plan):
        snapshots = tuple(self.service.store.load(s) for s in plan.frozen_snapshot_ids)
        prices = [s for s in snapshots if s.result.request.dataset == "daily"]
        for adjustment in {"raw", plan.adjustment}:
            candidates = [s for s in prices if s.result.request.adjustment == adjustment]
            if len(candidates) != 1:
                raise ValueError("exactly one raw/selected price snapshot required")
            r = candidates[0].result.request
            if (
                r.instruments != (plan.instrument,)
                or r.start != plan.date_start
                or r.end != plan.date_end
                or r.asof != plan.asof
            ):
                raise ValueError("frozen price window/asof mismatch")
        if any(
            s.result.request.instruments != (plan.instrument,) or s.result.request.asof != plan.asof
            for s in snapshots
        ):
            raise ValueError("frozen scope/asof mismatch")
        if len({s.result.request.adjustment for s in prices}) != len(prices):
            raise ValueError("ambiguous exhibit price basis")
        calendars = [s for s in snapshots if s.result.request.dataset == "calendar"]
        if len(calendars) != 1 or not (
            calendars[0].result.request.start <= plan.date_start
            and calendars[0].result.request.end >= plan.date_end
        ):
            raise ValueError("exactly one covering calendar required")
        return tuple(s.snapshot_id for s in snapshots)

    def start(self, investigation_id, plan):
        from marketpulse.investigation.domain.enums import AuditActorType
        from marketpulse.investigation.domain.reports import AuditEvent

        now = datetime.now(UTC)
        run_id = "RUN-QUANT-" + uuid.uuid4().hex[:16]
        settings = depth_settings(self.runner.settings, plan.depth)
        with self.service.sessions.begin() as session:
            for entity in (
                InvestigationRun(
                    run_id=run_id,
                    investigation_id=investigation_id,
                    mode=RunMode.LIVE,
                    status=RunStatus.RUNNING,
                    current_phase=WorkflowPhase.COLLECT,
                    checkpoint_version=0,
                    state_version=0,
                    workflow_version="quant-v1",
                    created_at=now,
                    started_at=now,
                    updated_at=now,
                ),
                RunBudget(
                    run_id=run_id,
                    max_research_rounds=settings.max_research_rounds,
                    max_search_calls=settings.max_search_queries,
                    max_fetch_calls=settings.max_pages,
                    max_model_calls=0,
                    max_tokens=0,
                    max_wall_time_ms=int(settings.total_timeout_seconds * 1000),
                    max_sources=settings.max_pages,
                    updated_at=now,
                ),
                AuditEvent(
                    audit_event_id="QPLAN-" + run_id,
                    investigation_id=investigation_id,
                    run_id=run_id,
                    actor_type=AuditActorType.SYSTEM,
                    event_type="QUANT_FROZEN_PLAN",
                    target_type="Run",
                    target_id=run_id,
                    metadata=plan.model_dump(mode="json"),
                    created_at=now,
                ),
            ):
                self.runner.repository.add_in_session(session, entity)
        self.runner.tasks[run_id] = asyncio.create_task(
            self.execute(run_id, investigation_id, plan)
        )
        return run_id

    async def execute(self, run_id, investigation_id, plan):
        from .acquisition import acquire_inputs
        from .domain import MetricSpec

        self.phases[run_id] = "取数"
        try:
            timeout = depth_settings(self.runner.settings, plan.depth).total_timeout_seconds
            async with asyncio.timeout(max(1, timeout - 30)):
                ids = (
                    await asyncio.to_thread(self.validate_pins, plan)
                    if plan.frozen_snapshot_ids
                    else await acquire_inputs(self, run_id, plan)
                )
                self.phases[run_id] = "冻结快照"
                for snapshot_id in ids:
                    await asyncio.to_thread(
                        self.service.store.attach, snapshot_id, investigation_id
                    )
                with self.service.sessions.begin() as session:
                    row = session.get(InvestigationRunRow, run_id)
                    row.current_phase = WorkflowPhase.ANALYZE
                    row.state_version += 1
                self.phases[run_id] = "确定性计算"
                await self.runner._execute_quant(
                    run_id=run_id,
                    spec=MetricSpec(
                        include_exhibits=True,
                        price_adjustment=plan.adjustment,
                        return_basis="price" if plan.adjustment == "raw" else "adjusted_proxy",
                        metrics=(
                            "return",
                            "cagr",
                            "volatility",
                            "drawdown",
                            "pe",
                            "pb",
                            "roe",
                            "trend",
                            "sharpe",
                            "beta",
                        ),
                        explicit_zero_risk_free=plan.rf == "zero",
                    ),
                    inputs=ids,
                    instrument_id=plan.instrument,
                    asof=plan.asof,
                    idempotency_key="public-quant-v1",
                )
        except asyncio.CancelledError:
            await self.runner._finalize_run(
                run_id,
                (
                    "SERVER_SHUTDOWN：服务关闭，保留冻结材料并生成部分报告。"
                    if self.runner._closing
                    else "USER_CANCELLED：已停止取数，保留冻结材料并生成部分报告。"
                ),
            )
        except Exception:
            await self.runner._finalize_run(
                run_id,
                "QUANT_PARTIAL：数据或时长不足，未完成部分不作为结论；请检查数据源与冻结区间。",
            )
        finally:
            self.phases[run_id] = "成稿"

    def presentation(self, run_id):
        from .charts import presentation

        return presentation(self.service, run_id)
