"""Domain-separated canonical semantic hashing for Phase 5 report governance.

Semantic hashes cover only canonical semantic content. Runtime identifiers,
timestamps, database row order, and display ordinals must never be included in
the payload handed to :func:`canonical_hash`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, JsonValue


def canonical_hash(domain: str, payload: object) -> str:
    """Return SHA-256 over the domain-separated canonical JSON of ``payload``.

    Canonicalization rules:
    - mapping keys are emitted in sorted order at every depth;
    - sets/frozensets become lists sorted by their canonical JSON form;
    - tuples become lists (order preserved);
    - pydantic models are dumped in JSON mode first;
    - enums serialize to their values; datetimes/dates to ISO format.
    """
    canonical = _canonicalize(payload)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(f"{domain}\x00{encoded}".encode()).hexdigest()


def _canonicalize(value: object) -> JsonValue:
    if isinstance(value, BaseModel):
        return _canonicalize(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        items = [_canonicalize(item) for item in value]
        return sorted(items, key=_canonical_sort_key)
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"value of type {type(value).__name__} is not canonically hashable")


def _canonical_sort_key(item: JsonValue) -> str:
    return json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
