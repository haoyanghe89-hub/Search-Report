from __future__ import annotations

import asyncio
import json
from typing import Literal

from pydantic import model_validator

from .contracts import digest
from .domain import ArtifactBundle, FrozenModel, MetricSpec
from .evidence import ComputationEvidence, build_computation_evidence
from .execution.service import check_bundle


class ComputationValidation(FrozenModel):
    validation_hash: str
    cell_hash: str
    artifact_id: str
    reproduction: str
    exact_entailment: bool
    integrity: bool
    sample_valid: bool
    calibrated: bool
    independent_families: int
    adequate_sources: int
    rights_valid: bool
    pit_valid: bool
    conflict_free: bool
    importance: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    policy_version: str = "quant-validation-v1"
    status: Literal["VERIFIED", "UNVERIFIED"]
    missing: tuple[str, ...]

    @model_validator(mode="after")
    def validate_identity(self):
        material = self.model_dump(mode="json", exclude={"validation_hash"})
        if digest(material) != self.validation_hash:
            raise ValueError("computation validation hash mismatch")
        return self


def compare_reproduction(old: ArtifactBundle, new: ArtifactBundle, spec: MetricSpec):
    check_bundle(old)
    check_bundle(new)
    a, b = json.loads(old.manifest_json), json.loads(new.manifest_json)
    environment_a, environment_b = a.pop("environment"), b.pop("environment")
    a.pop("output_hash")
    b.pop("output_hash")
    if a != b:
        raise ValueError("reproduction input/definition drift")
    if (
        environment_a["source_tree_hash"] != environment_b["source_tree_hash"]
        or environment_a["lock_hash"] != environment_b["lock_hash"]
    ):
        raise ValueError("frozen code or dependency lock unavailable")
    if environment_a == environment_b:
        if old.output_hash != new.output_hash:
            raise ValueError("same-environment output bytes differ")
        return
    if len(old.values) != len(new.values):
        raise ValueError("reproduction cells differ")
    for left, right in zip(old.values, new.values, strict=False):
        if left.model_dump(exclude={"value"}) != right.model_dump(exclude={"value"}):
            raise ValueError("cell unit/time/definition drift")
        if (left.value is None) != (right.value is None):
            raise ValueError("cell null drift")
        if left.value is None:
            continue
        tolerance = (
            spec.relative_tolerance * abs(left.value)
            if left.name in {"pe", "pb"}
            else spec.absolute_tolerance
        )
        if abs(left.value - right.value) > tolerance:
            raise ValueError("reproduction numeric tolerance exceeded")


def verify_cell(bundle: ArtifactBundle, evidence: ComputationEvidence):
    expected = build_computation_evidence(bundle, metric_path=evidence.metric_path)
    if evidence != expected:
        raise ValueError("computation cell/lineage binding mismatch")


async def verify_computation_claim(
    service, *, job_id: str, evidence: ComputationEvidence, importance: str = "HIGH"
) -> ComputationValidation:
    bundle = await asyncio.to_thread(service.bundle_for, job_id)
    verify_cell(bundle, evidence)
    reproduced = await service.reproduce(job_id=job_id)
    request = await asyncio.to_thread(service.input_for, job_id)
    compare_reproduction(bundle, reproduced, request.spec)
    cell = bundle.values[int(evidence.metric_path.split("/")[-1])]
    inputs = request.snapshots
    # Wrappers are never independent. Only verified original producer lineage counts.
    required_datasets = (
        {"daily", "financial"}
        if (
            cell.name in {"pe", "pb", "roe", "net_profit_growth", "revenue_growth"}
            or cell.name.startswith("disclosed_")
            or "disclosed_relative_difference" in cell.name
        )
        else {"daily"}
    )
    price_basis = (
        "raw"
        if "financial" in required_datasets or request.spec.return_basis == "price"
        else request.spec.price_adjustment or "qfq"
    )
    support = [
        s
        for s in inputs
        if s.result.request.dataset in required_datasets
        and (
            s.result.request.dataset != "daily"
            or (
                s.result.request.adjustment == price_basis
                and s.result.request.start <= cell.start
                and s.result.request.end >= cell.end
            )
        )
    ]
    families = {
        s.result.source_family
        for s in support
        if s.result.lineage_status == "verified" and s.result.source_family != "unknown_market_feed"
    }
    adequate = {
        s.result.source_family
        for s in support
        if s.result.lineage_status == "verified"
        and json.loads(s.result.provenance_json).get("quality_score", 0) >= 0.6
        and s.result.source_family in families
    }
    rights = all(
        s.result.rights.entitlement != "unknown"
        and s.result.rights.license_reference
        and s.result.rights.scope.value == "internal_research"
        and (s.result.rights.expires_at is None or request.asof < s.result.rights.expires_at)
        for s in inputs
    )
    pit = all(s.result.pit.value == "STRICT" for s in inputs)
    conflict_free = not any(
        "claims_paused" in s.result.quality_flags
        or json.loads(s.result.crosscheck_json).get("conflicts")
        for s in inputs
    )
    sample = cell.sample_count >= request.spec.minimum_observations
    # Current implementation has golden hand-calculated fixtures for these scalar formulas.
    calibrated = cell.name in {"return", "volatility", "drawdown", "pe", "pb", "roe"}
    required = 2 if importance in {"HIGH", "CRITICAL"} else 1
    # Financial and price feeds must each meet the threshold, not add unlike
    # price+profit producers together and pretend they corroborate one another.
    independence = min(
        (
            len(
                {
                    s.result.source_family
                    for s in support
                    if s.result.request.dataset == dataset
                    and s.result.lineage_status == "verified"
                    and s.result.source_family in families
                }
            )
            for dataset in required_datasets
        ),
        default=0,
    )
    quality_count = min(
        (
            len(
                {
                    s.result.source_family
                    for s in support
                    if s.result.request.dataset == dataset and s.result.source_family in adequate
                }
            )
            for dataset in required_datasets
        ),
        default=0,
    )
    calendar_valid = any(
        s.result.request.dataset == "calendar"
        and s.result.request.start <= cell.start
        and s.result.request.end >= cell.end
        for s in inputs
    )
    instrument = json.loads(request.instrument_definition_json)
    rules_valid = any(
        rule["effective_from"] <= cell.start.isoformat()
        and (rule["effective_to"] is None or rule["effective_to"] >= cell.end.isoformat())
        for rule in instrument["rules"]
    )
    missing = tuple(
        key
        for key, passes in (
            ("missing_value", cell.value is not None),
            ("sample", sample),
            ("calibration", calibrated),
            ("independence", independence >= required),
            ("source_quality", quality_count >= required),
            ("rights", rights),
            ("PIT", pit),
            ("conflict", conflict_free),
            ("stale", not any(s.stale for s in inputs)),
            ("calendar", calendar_valid),
            ("market_rules", rules_valid),
        )
        if not passes
    )
    material = dict(
        policy_version="quant-validation-v1",
        cell_hash=evidence.cell_hash,
        artifact_id=bundle.artifact_id,
        reproduction="REPRODUCIBLE",
        exact_entailment=cell.value is not None,
        integrity=True,
        sample_valid=sample,
        calibrated=calibrated,
        independent_families=independence,
        adequate_sources=quality_count,
        rights_valid=bool(rights),
        pit_valid=pit,
        conflict_free=conflict_free,
        importance=importance,
        status="VERIFIED" if not missing else "UNVERIFIED",
        missing=missing,
    )
    return ComputationValidation(validation_hash=digest(material), **material)
