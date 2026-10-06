"""Allowlisted evidence exhibits over integrity-checked immutable output cells."""

import json

from sqlalchemy import select

from marketpulse.investigation.persistence.models import ClaimRow, ValidationResultRow

from .evidence import build_computation_evidence
from .execution.service import check_bundle, check_input_binding
from .reporting import load_material
from .storage.models import ComputeJobRow, SnapshotOwnershipRow
from .validation import verify_cell


def presentation(service, run_id):
    with service.sessions() as session:
        material = load_material(session, run_id)
        if not material:
            return {}
        if not material.claims:
            return dict(gaps=material.limitations, completeness=material.completeness)
        job = session.get(ComputeJobRow, material.job_id)
        if (
            not job
            or job.run_id != run_id
            or job.status != "COMPLETED"
            or job.artifact_id != material.artifact_id
        ):
            raise ValueError("job/material mismatch")
        bundle = service.bundle_for(job.job_id)
        check_bundle(bundle)
        check_input_binding(bundle, service.input_for(job.job_id))
        if (
            bundle.output_hash != material.output_hash
            or bundle.manifest_hash != material.manifest_hash
        ):
            raise ValueError("material artifact hash mismatch")
        from marketpulse.investigation.persistence.models import InvestigationRunRow

        owner = session.get(InvestigationRunRow, run_id).investigation_id
        for snapshot_id in bundle.input_snapshot_ids:
            if not session.get(SnapshotOwnershipRow, (owner, snapshot_id)):
                raise PermissionError("input ownership missing")
            service.store.load(snapshot_id)
        statuses = {}
        for claim in material.claims:
            persisted = session.scalar(
                select(ClaimRow).where(
                    ClaimRow.run_id == run_id, ClaimRow.statement == claim.statement
                )
            )
            validation = (
                session.get(ValidationResultRow, persisted.latest_validation_id)
                if persisted
                else None
            )
            if (
                not validation
                or validation.validation_basis_payload.get("computation")
                != claim.validation.model_dump(mode="json")
                or str(persisted.validation_status) != claim.validation.status
            ):
                raise ValueError("latest validation drift")
            verify_cell(bundle, claim.evidence)
            if not claim.validation.integrity or claim.validation.reproduction != "REPRODUCIBLE":
                raise ValueError("unvalidated artifact")
            statuses[claim.evidence.metric_path] = claim.validation.status
        from .storage.models import QuantCitationRow

        citations = session.scalars(select(QuantCitationRow)).all()
        citation_by_path = {
            c.payload.get("canonical_locator", {}).get("metric_path"): c.citation_id
            for c in citations
            if c.payload.get("canonical_locator", {}).get("artifact_id") == bundle.artifact_id
        }
    values = []
    manifest = json.loads(bundle.manifest_json)
    providers = {s["snapshot_id"]: s["provider"] for s in manifest["inputs"]}
    for index, value in enumerate(bundle.values):
        path = f"/values/{index}"
        ev = build_computation_evidence(bundle, metric_path=path)
        values.append(
            dict(
                **value.model_dump(mode="json"),
                metric_path=path,
                cell_hash=ev.cell_hash,
                artifact_id=bundle.artifact_id,
                status=statuses.get(path, "UNVERIFIED"),
                citation_id=citation_by_path.get(path),
                provider=providers.get(value.row_keys[-1]) if value.row_keys else None,
            )
        )

    def series(names):
        result = []
        for name in names:
            cells = [
                v
                for v in values
                if v["name"] == name and (name.startswith("chart_") or v["value"] is not None)
            ]
            if cells and any(v["value"] is not None for v in cells):
                result.append(
                    dict(
                        name=name,
                        unit=cells[0]["unit"],
                        points=[
                            dict(
                                x=v["row_keys"][0] if v["row_keys"] else v["end"],
                                value=v["value"],
                                missing_reason=v["missing_reason"],
                                metric_path=v["metric_path"],
                                cell_hash=v["cell_hash"],
                                citation_id=v["citation_id"],
                                label=(v["name"] + " · " + (v["provider"] or "independent")),
                            )
                            for v in cells
                        ],
                    )
                )
        return result

    charts = []
    for key, title, names, note in (
        (
            "price",
            "价格与回撤",
            [f"chart_{kind}_{a}" for a in ("raw", "qfq", "hfq") for kind in ("price", "drawdown")],
            "价格而非策略净值；复权使用冻结 anchor，回撤为价格/历史最高价格−1；不含未收盘 bar。",
        ),
        (
            "valuation",
            "估值口径对照",
            ["pe", "pb", "disclosed_pe_ttm", "disclosed_pb_mrq"],
            "独立计算为raw价格×同日总发行股数/TTM归母净利或归母总权益；披露值分列，不平均、不排名。",
        ),
        (
            "financial",
            "财务报告期趋势",
            ["chart_parent_net_profit_growth", "chart_revenue_growth"],
            "fraction；同报告期累计金额同比，年报与年报、相同累计季度与上年同期比较，不年化。"
            "当前回溯版本并非STRICT PIT。",
        ),
    ):
        data = series(names)
        if data:
            charts.append(
                dict(
                    exhibit_id=f"EXHIBIT-Q·{len(charts) + 1}",
                    kind=key,
                    title=title,
                    note=note,
                    artifact_id=bundle.artifact_id,
                    output_hash=bundle.output_hash,
                    asof=material.asof,
                    status="UNVERIFIED",
                    series=data,
                    render_version="quant-chart-v1",
                )
            )
    drawdown = next((v for v in values if v["name"] == "drawdown"), None)
    if charts and charts[0]["kind"] == "price" and drawdown:
        charts[0]["drawdown"] = {
            k: drawdown[k] for k in ("peak_date", "trough_date", "recovery_date", "metric_path")
        }
    return dict(
        values=values,
        charts=charts[:3],
        gaps=material.limitations,
        evidence_count=len(material.claims),
        citation_count=len(citation_by_path),
        completeness=material.completeness,
        manifest_hash=bundle.manifest_hash,
        output_hash=bundle.output_hash,
        input_snapshot_ids=bundle.input_snapshot_ids,
        asof=material.asof,
        methodology=manifest["spec"],
    )
