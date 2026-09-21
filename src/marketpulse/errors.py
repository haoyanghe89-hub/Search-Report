from __future__ import annotations

from enum import IntEnum


class ErrorCode(IntEnum):
    INVALID_INPUT = 2
    CONFIG_ERROR = 3
    SEARCH_UNAVAILABLE = 10
    NO_USABLE_EVIDENCE = 11
    TIMEOUT = 12
    OUTPUT_WRITE_FAILED = 13
    INTERNAL_ERROR = 20


class MarketPulseError(Exception):
    def __init__(self, message: str, code: ErrorCode) -> None:
        super().__init__(message)
        self.code = code


class ConfigurationError(MarketPulseError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorCode.CONFIG_ERROR)


class InvalidInputError(MarketPulseError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorCode.INVALID_INPUT)


class SearchUnavailableError(MarketPulseError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorCode.SEARCH_UNAVAILABLE)


class NoUsableEvidenceError(MarketPulseError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorCode.NO_USABLE_EVIDENCE)


class WorkflowTimeoutError(MarketPulseError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorCode.TIMEOUT)


class OutputWriteError(MarketPulseError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorCode.OUTPUT_WRITE_FAILED)


class BudgetExceeded(MarketPulseError):
    def __init__(self, dimension: str) -> None:
        self.dimension = dimension
        super().__init__(f"运行预算已耗尽: {dimension}", ErrorCode.TIMEOUT)
