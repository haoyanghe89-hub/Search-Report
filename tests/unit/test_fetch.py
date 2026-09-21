from __future__ import annotations

import socket
from typing import Any

import pytest

from marketpulse.adapters.fetch import _is_public_host


def _dns_result(address: str) -> list[tuple[Any, ...]]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]


@pytest.mark.asyncio
async def test_proxy_dns_range_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_: _dns_result("198.18.0.42"))
    assert not await _is_public_host("example.com")
    assert await _is_public_host("example.com", allow_proxy_dns=True)


@pytest.mark.asyncio
async def test_proxy_dns_mode_still_rejects_private_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_: _dns_result("10.0.0.8"))
    assert not await _is_public_host("internal.example", allow_proxy_dns=True)
