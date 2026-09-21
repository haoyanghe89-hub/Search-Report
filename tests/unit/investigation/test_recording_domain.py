from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.investigation.domain.enums import ExternalCallStatus
from marketpulse.investigation.domain.recordings import RecordedToolCall

NOW = datetime(2026, 9, 21, tzinfo=UTC)
HASH = hashlib.sha256(b"payload").hexdigest()
REF = BlobRef(HASH)


def _call(**changes: object) -> RecordedToolCall:
    values: dict[str, object] = {
        "call_id": "TC-001",
        "run_id": "RUN-001",
        "step_id": "STEP-001",
        "operation": "search",
        "request_fingerprint": HASH,
        "request_blob_ref": REF,
        "request_hash": HASH,
        "response_blob_ref": REF,
        "response_hash": HASH,
        "tool_name": "search",
        "provider": "fixture",
        "schema_version": "search-v1",
        "config_version": "runtime-v1",
        "attempt": 1,
        "status": ExternalCallStatus.SUCCESS,
        "replayable": True,
        "recorded_at": NOW,
        "completed_at": NOW + timedelta(seconds=1),
    }
    values.update(changes)
    return RecordedToolCall.model_validate(values)


def test_successful_recording_requires_complete_response_payload() -> None:
    assert _call().replayable is True
    with pytest.raises(ValidationError, match="response payload"):
        _call(response_blob_ref=None, response_hash=None)


def test_failed_recording_can_omit_response_but_is_never_replayable() -> None:
    failure = _call(
        status=ExternalCallStatus.TIMEOUT,
        replayable=False,
        response_blob_ref=None,
        response_hash=None,
        error_code="UPSTREAM_TIMEOUT",
    )
    assert failure.status is ExternalCallStatus.TIMEOUT
    assert failure.response_blob_ref is None

    with pytest.raises(ValidationError, match="failed call cannot be replayable"):
        _call(status=ExternalCallStatus.PROVIDER_ERROR, replayable=True)


def test_recording_rejects_partial_response_pair_and_invalid_timestamps() -> None:
    with pytest.raises(ValidationError, match="provided together"):
        _call(response_blob_ref=None)
    with pytest.raises(ValidationError, match="completed_at"):
        _call(completed_at=NOW - timedelta(seconds=1))


def test_recording_attempt_is_positive() -> None:
    with pytest.raises(ValidationError):
        _call(attempt=0)
