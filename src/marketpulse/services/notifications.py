from __future__ import annotations

import asyncio
import logging
from typing import Any

from marketpulse.domain.collaboration import BlackboardEvent


class ProgressNotifier:
    """Redis is a disposable wake-up hint. Readers always reload the SQL blackboard."""

    def __init__(self, redis_url: str | None = None) -> None:
        self.client: Any = None
        if redis_url:
            from redis.asyncio import Redis

            self.client = Redis.from_url(
                redis_url,
                socket_connect_timeout=1,
                socket_timeout=1,
            )

    async def publish(self, event: BlackboardEvent) -> None:
        if self.client is None:
            return
        try:
            async with asyncio.timeout(1.5):
                await self.client.publish(
                    f"marketpulse:runs:{event.run_id}", event.model_dump_json()
                )
        except Exception:
            # Never log Redis exceptions: their connection strings may contain secrets.
            logging.getLogger("marketpulse").warning(
                "Redis progress unavailable; SQL state remains authoritative"
            )

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
