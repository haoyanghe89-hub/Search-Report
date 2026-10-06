"""Lossless wire-shape repair using only the exact trusted analysis input."""

from __future__ import annotations

from typing import Any

from marketpulse.investigation.agents.contracts import AnalysisInput


def normalize_existing_claim_references(payload: Any, request: AnalysisInput) -> Any:
    """Make known existing Claims local; never drop or remap unknown references.

    Models sometimes attach evidence to an existing input Claim without including
    its unchanged definition in claims. Copying that definition is structural
    normalization only: relation stance, quotes and verification remain unchanged.
    """
    if not isinstance(payload, dict):
        return payload
    claims = payload.get("claims", [])
    relations = payload.get("relations", [])
    observations = payload.get("conflict_observations", [])
    if not all(isinstance(items, list) for items in (claims, relations, observations)):
        return payload
    local = {item.get("claim_key") for item in claims if isinstance(item, dict)}
    known = {item.claim_key: item for item in request.existing_claims}
    claims = list(claims)
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        existing = known.get(claim.get("claim_key"))
        if existing is None:
            claims[index] = normalize_new_claim_qualifiers(claim)
            continue
        if not _has_qualifier_groups(existing.qualifiers):
            continue
        if (
            claim.get("statement") == existing.statement
            and claim.get("claim_type") == existing.claim_type.value
            and claim.get("entity_qualifiers") == existing.qualifiers
            and not claim.get("time_qualifiers")
            and not claim.get("scope_qualifiers")
        ):
            # An exact copy of the full stored qualifier envelope was nested in entity.
            # Unwrap that envelope; never substitute changed/partial qualifiers.
            claims[index] = {**claim, **_qualifier_fields(existing.qualifiers)}
    additions = []
    for item in [*relations, *observations]:
        if not isinstance(item, dict):
            continue
        key = item.get("claim_key")
        if not isinstance(key, str) or key in local or key not in known:
            continue
        existing = known[key]
        if not _has_qualifier_groups(existing.qualifiers):
            continue  # A legacy/partial definition cannot be reconstructed losslessly.
        additions.append(
            {
                "claim_key": key,
                "statement": existing.statement,
                "claim_type": existing.claim_type.value,
                **_qualifier_fields(existing.qualifiers),
            }
        )
        local.add(key)
    return {**payload, "claims": [*claims, *additions]}


def _has_qualifier_groups(qualifiers: dict) -> bool:
    return all(isinstance(qualifiers.get(group), dict) for group in ("entity", "time", "scope"))


def _qualifier_fields(qualifiers: dict) -> dict:
    return {f"{group}_qualifiers": qualifiers[group] for group in ("entity", "time", "scope")}


def normalize_new_claim_qualifiers(claim: dict) -> dict:
    """Translate supplied wire fields only; never extract/guess facts from prose."""
    envelope = claim.get("qualifiers", {})
    if not isinstance(envelope, dict):
        return claim  # Strict schema rejects malformed fields.
    result = {k: v for k, v in claim.items() if k != "qualifiers"}
    groups = {}
    for group in ("entity", "time", "scope"):
        supplied = result.get(f"{group}_qualifiers", {})
        nested = envelope.get(group, {})
        if group in ("time", "scope") and not isinstance(nested, dict):
            nested = {}
        if not isinstance(supplied, dict) or not isinstance(nested, dict):
            return claim
        if any(k in supplied and supplied[k] != v for k, v in nested.items()):
            raise ValueError("conflicting structured qualifier fields")
        groups[group] = {**nested, **supplied}
    placements = {
        "value": "entity",
        "unit": "entity",
        "time": "time",
        "scope": "scope",
        "definition": "scope",
        "methodology": "scope",
        "provenance": "scope",
    }
    for key, value in envelope.items():
        if key not in groups or not isinstance(value, dict):
            group = placements.get(key, "entity")
            if key in groups[group] and groups[group][key] != value:
                raise ValueError("conflicting structured qualifier fields")
            groups[group][key] = value
    aliases = {
        "value": ("numeric_value",),
        "time": ("as_of", "date"),
        "scope": ("benchmark",),
        "definition": ("metric",),
        "methodology": ("method",),
        "provenance": ("data_provenance",),
    }
    for canonical, names in aliases.items():
        group = groups[placements[canonical]]
        if canonical not in group:
            values = [g[n] for g in groups.values() for n in names if n in g]
            if values and all(v == values[0] for v in values):
                group[canonical] = values[0]
    return {**result, **{f"{g}_qualifiers": v for g, v in groups.items()}}
