"""Allowlisted error categories; never persist exception text, bodies, URLs or headers."""

import re

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import JsonValue

_FETCH_REASONS = frozenset(
    {
        "NON_PUBLIC_DNS",
        "UNSAFE_URL",
        "HTTP_FORBIDDEN",
        "HTTP_RATE_LIMITED",
        "HTTP_ERROR",
        "CHALLENGE_PAGE",
        "REDIRECT_ERROR",
        "MIME_NOT_ALLOWED",
        "BODY_TOO_LARGE",
    }
)


def provider_diagnostics(error: BaseException) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    values = getattr(error, "diagnostics", {})
    if (
        isinstance(values, dict)
        and isinstance(values.get("reason"), str)
        and values["reason"] in _FETCH_REASONS
    ):
        result["reason"] = values["reason"]
        domain = values.get("domain")
        if isinstance(domain, str) and re.fullmatch(r"[a-zA-Z0-9.-]{1,253}", domain):
            result["domain"] = domain
        for key, lower, upper in (("http_status", 100, 599), ("html_bytes", 0, 64 * 1024 * 1024)):
            value = values.get(key)
            if type(value) is int and lower <= value <= upper:
                result[key] = value
    current: BaseException | None = error
    # Bound traversal even if an exception has a cyclic cause chain.
    for _ in range(8):
        if current is None:
            break
        if isinstance(current, APIStatusError):
            result.setdefault("category", "http_error")
            if type(current.status_code) is int and 100 <= current.status_code <= 599:
                result.setdefault("http_status", current.status_code)
        elif isinstance(current, (APITimeoutError, TimeoutError)):
            result.setdefault("category", "timeout")
        elif isinstance(current, (APIConnectionError, ConnectionError)):
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
