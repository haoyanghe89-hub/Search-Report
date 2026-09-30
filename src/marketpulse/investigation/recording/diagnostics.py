"""Allowlisted error categories; never persist exception text, bodies, URLs or headers."""

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import JsonValue


def provider_diagnostics(error: BaseException) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    current: BaseException | None = error
    # Bound traversal even if an exception has a cyclic cause chain.
    for _ in range(8):
        if current is None:
            break
        if isinstance(current, APIStatusError):
            result.setdefault("category", "http_error")
            if type(current.status_code) is int and 100 <= current.status_code <= 599:
                result.setdefault("http_status", current.status_code)
        elif isinstance(current, APITimeoutError):
            result.setdefault("category", "timeout")
        elif isinstance(current, APIConnectionError):
            result.setdefault("category", "connection_error")
        for error_type, category in (
            (httpx.TimeoutException, "timeout"),
            (httpx.ConnectError, "connect_error"),
            (httpx.ReadError, "read_error"),
            (httpx.WriteError, "write_error"),
            (httpx.ProtocolError, "protocol_error"),
            (httpx.ProxyError, "proxy_error"),
        ):
            if isinstance(current, error_type):
                result.setdefault("transport_category", category)
                break
        current = current.__cause__
    return result
