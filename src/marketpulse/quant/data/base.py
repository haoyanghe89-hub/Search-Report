from __future__ import annotations

import asyncio
import json
import os
import sys
from contextvars import ContextVar
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..contracts import CallContext, canonical, digest
from ..domain import DataRequest, DataResult, DataRights
from .calendar import VerifiedCalendar
from .instruments import InstrumentMaster
from .normalize import normalize
from .pit import classify
from .quality import quality_flags

RECORDED_SCOPE: ContextVar[bool] = ContextVar("quant_recorded_scope", default=False)


async def bounded_read(stream, cap: int) -> bytes:
    chunks = []
    size = 0
    while chunk := await stream.read(65536):
        size += len(chunk)
        if size > cap:
            raise ProviderUnavailable("worker output limit exceeded")
        chunks.append(chunk)
    return b"".join(chunks)


class ProviderUnavailable(RuntimeError):
    pass


class IsolatedSDKAdapter:
    provider: str
    upstream: str

    def __init__(
        self, master: InstrumentMaster, calendar: VerifiedCalendar, python: str | None = None
    ) -> None:
        self.master, self.calendar, self.python = master, calendar, python or sys.executable

    async def _call(self, query: dict, budget: float) -> dict:
        child = await asyncio.create_subprocess_exec(
            self.python,
            "-m",
            "marketpulse.quant.data.worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        try:
            async with asyncio.timeout(budget):
                child.stdin.write(canonical(query).encode())
                await child.stdin.drain()
                child.stdin.close()
                stdout, _ = await asyncio.gather(
                    bounded_read(child.stdout, 16 * 1024 * 1024),
                    bounded_read(child.stderr, 1024 * 1024),
                )
                await child.wait()
        except BaseException:
            if child.returncode is None:
                child.kill()
            await child.wait()
            raise
        if child.returncode or len(stdout) > 16 * 1024 * 1024:
            raise ProviderUnavailable("isolated SDK failed")
        lines = [line for line in stdout.splitlines() if line.startswith(b"QUANT_JSON:")]
        if not lines:
            raise ProviderUnavailable("missing worker result")
        payload = json.loads(lines[-1][11:])
        if payload.get("error"):
            raise ProviderUnavailable(payload["error"])
        return payload

    async def fetch(self, request: DataRequest, context: CallContext) -> DataResult:
        if not RECORDED_SCOPE.get():
            raise RuntimeError("SDK calls must use RecordingQuantDataPort")
        if request.scope.value != "internal_research":
            raise PermissionError("unlicensed provider scope")
        if len(request.instruments) != 1:
            raise ValueError("P0 accepts one instrument per recorded request")
        alias = self.master.alias(request.instruments[0], request.start)
        last = self.master.alias(request.instruments[0], request.end)
        if last != alias:
            raise ValueError("request crosses an alias change; split into recorded requests")
        if self.calendar.verification.exchange != alias.exchange:
            raise ValueError("calendar exchange mismatch")
        sessions = (
            self.calendar.sessions(request.start, request.end)
            if request.dataset in {"daily", "valuation"}
            else ()
        )
        query = {
            "provider": self.provider,
            "code": alias.code,
            "exchange": alias.exchange,
            "request": request.model_dump(mode="json"),
        }
        payload = await self._call(query, context.budget_seconds)
        raw = payload["rows"]
        factors = payload.get("factors", [])
        source_units = payload.get("source_units", {})
        rows, units = normalize(raw, request, self.provider, request.instruments[0], source_units)
        if request.dataset == "financial":
            retained = []
            for row in rows:
                published = row.get("published_at")
                available = None
                if published:
                    day = datetime.fromisoformat(published).date() + timedelta(days=1)
                    future = self.calendar.sessions(day, self.calendar.verification.end)
                    if future:
                        available = datetime.combine(
                            future[0], time(9, 30), ZoneInfo("Asia/Shanghai")
                        )
                    if available is None and request.normalizer_version == "3":
                        row["availability_basis"] = "calendar_unavailable_not_first_seen"
                    elif available is None or available > request.asof:
                        continue
                row.update(
                    available_at=available.isoformat() if available else None,
                    first_seen_at=datetime.now(UTC).isoformat(),
                    revision_id="unknown",
                    currency="CNY" if self.provider == "baostock" else "unknown",
                    statement_basis="provider_unspecified",
                    audit_status="unknown",
                    source_hash=digest(raw),
                )
                if request.normalizer_version == "3-parent-2":
                    row.update(currency="CNY", statement_basis="parent")
                retained.append(row)
            rows = retained
        if request.dataset == "daily" and request.adjustment != "raw":
            from .adjustments import anchored_prices

            if self.provider != "baostock" or not factors:
                raise ProviderUnavailable("adjusted feed has no verified historical anchor")
            rows = anchored_prices(rows, factors, request)
        excluded = 0
        if request.dataset in {"daily", "valuation"}:
            retained = []
            for row in rows:
                day = datetime.fromisoformat(row["date"]).date()
                if day not in sessions:
                    raise ProviderUnavailable("provider returned unverified session")
                provisional = not self.calendar.complete(day, request.asof)
                if provisional and request.complete_sessions_only:
                    excluded += 1
                    continue
                row["provisional"] = provisional
                retained.append(row)
            rows = retained
        flags = set(quality_flags(rows, request.dataset))
        if request.dataset == "adjustment" and not rows:
            flags.discard("empty_dataset")
            flags.add("no_actions_in_range")
        if request.dataset == "daily":
            observed = {datetime.fromisoformat(row["date"]).date() for row in rows}
            expected = {day for day in sessions if self.calendar.complete(day, request.asof)}
            if expected - observed:
                flags.add("missing_sessions")
            if any(row.get("trading_status") is None or row.get("is_st") is None for row in rows):
                flags.add("status_unavailable")
        for field in request.fields:
            if any(field not in row or row[field] is None for row in rows):
                flags.add("requested_field_missing:" + field)
        if excluded:
            flags.add("incomplete_sessions_excluded")
        if (
            self.provider.startswith("akshare")
            and request.dataset == "financial"
            and request.normalizer_version != "3-parent-2"
        ):
            flags.add("unknown_financial_units")
        if request.normalizer_version == "3-parent-2":
            flags.add("retrospective_revision_not_strict_pit")
            if request.dataset == "valuation":
                flags.add("share_announcement_unavailable")
        if not rows and request.dataset != "adjustment":
            raise ProviderUnavailable("empty dataset after normalization")
        return DataResult(
            provider=self.provider,
            upstream=self.upstream,
            request=request,
            retrieved_at=datetime.now(UTC),
            records_json=canonical(rows),
            raw_records_json=canonical(raw),
            units=units,
            quality_flags=tuple(sorted(flags)),
            pit=classify(request.dataset, self.provider, rows),
            rights=DataRights(
                policy_id=f"{self.provider}:unknown:v1",
                provider=self.provider,
                upstream=self.upstream,
                attribution=self.upstream,
            ),
            adjustment_factor_hash=digest(factors)
            if factors
            else digest(raw)
            if request.dataset == "adjustment"
            else None,
            provenance_json=canonical(
                {
                    "calendar": self.calendar.verification.model_dump(mode="json"),
                    "instrument": self.master.get(request.instruments[0]).model_dump(mode="json"),
                    "factors": factors,
                    "source_units": source_units,
                    "price_basis": request.adjustment,
                    "valuation_basis": "supplier_raw_pe_ttm_pb_mrq_not_recomputed",
                    "factor_hash": digest(factors) if factors else None,
                }
            ),
        )
