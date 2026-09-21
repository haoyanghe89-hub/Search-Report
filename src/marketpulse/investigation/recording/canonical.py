from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from marketpulse.investigation.ports.external import ModelRequest, response_schema


def canonical_request(operation: str, request: BaseModel) -> bytes:
    envelope: dict[str, Any] = {
        "operation": operation,
        "request": request.model_dump(mode="json", exclude={"response_model"}),
    }
    if isinstance(request, ModelRequest):
        envelope["response_schema"] = response_schema(request)
    return json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def request_fingerprint(operation: str, request: BaseModel) -> str:
    return hashlib.sha256(canonical_request(operation, request)).hexdigest()


def canonical_response(response: BaseModel) -> bytes:
    return response.model_dump_json(indent=None).encode("utf-8")
