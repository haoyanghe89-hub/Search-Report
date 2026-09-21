from __future__ import annotations


class ExternalCallError(RuntimeError):
    code = "EXTERNAL_CALL_ERROR"


class ProviderCallError(ExternalCallError):
    code = "PROVIDER_ERROR"


class RateLimitedError(ExternalCallError):
    code = "RATE_LIMITED"


class InvalidProviderResponseError(ExternalCallError):
    code = "INVALID_RESPONSE"


class SecurityBlockedError(ExternalCallError):
    code = "SECURITY_BLOCKED"


class ReplayCacheMissError(ExternalCallError):
    code = "REPLAY_CACHE_MISS"

    def __init__(self, *, operation: str, request_fingerprint: str) -> None:
        self.operation = operation
        self.request_fingerprint = request_fingerprint
        super().__init__(f"{self.code}: {operation} {request_fingerprint}")
