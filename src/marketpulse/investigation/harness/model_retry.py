"""Only read-only structured inference may opt into possible duplicate billing."""

from marketpulse.investigation.harness.model_call_journal import ModelCallOutcomeUnknownError
from marketpulse.investigation.recording.diagnostics import provider_diagnostics
from marketpulse.investigation.recording.errors import ExternalCallError, RateLimitedError


class ModelRetryExhaustedError(ExternalCallError):
    code = "MODEL_RETRY_EXHAUSTED"


def retryable_model_error(error: BaseException) -> bool:
    diagnostics = provider_diagnostics(error)
    status = diagnostics.get("http_status")
    if status is not None:
        return status == 429 or 500 <= status <= 599
    return isinstance(error, (TimeoutError, ModelCallOutcomeUnknownError, RateLimitedError)) or (
        diagnostics.get("category") in {"timeout", "connection_error"}
        or diagnostics.get("transport_category") is not None
    )
