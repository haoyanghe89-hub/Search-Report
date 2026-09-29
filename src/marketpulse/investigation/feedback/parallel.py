"""Bounded parallel work with deterministic output order and structured cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


async def bounded_map(
    items: Sequence[T], worker: Callable[[T], Awaitable[R]], limit: int
) -> list[R]:
    if limit < 1:
        raise ValueError("parallel limit must be positive")
    semaphore = asyncio.Semaphore(limit)

    async def invoke(item: T) -> R:
        async with semaphore:
            return await worker(item)

    tasks = [asyncio.create_task(invoke(item)) for item in items]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
