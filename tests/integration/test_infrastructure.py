from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from marketpulse.domain.collaboration import BlackboardEvent, BlackboardState
from marketpulse.services.blackboard import BlackboardStore, StaleBlackboardWrite, events, runs
from marketpulse.services.notifications import ProgressNotifier


@pytest.mark.infrastructure
def test_postgres_blackboard() -> None:
    url = os.getenv("MARKETPULSE_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set MARKETPULSE_TEST_POSTGRES_URL to a dedicated test database")
    board = BlackboardStore(url)
    run_id = f"test_{uuid.uuid4().hex}"
    try:
        state = BlackboardState(run_id=run_id, topic="test research", competitor_limit=3)
        board.create(state)
        stale = board.load(run_id)
        state.warnings.append("persisted")
        board.save(state, "master", "plan.completed")
        with pytest.raises(StaleBlackboardWrite):
            board.save(stale, "search", "stale")
        assert board.load(run_id).warnings == ["persisted"]
        assert len(board.history(run_id)) == 2
    finally:
        with board.engine.begin() as connection:
            connection.execute(events.delete().where(events.c.run_id == run_id))
            connection.execute(runs.delete().where(runs.c.run_id == run_id))
        board.close()


@pytest.mark.infrastructure
@pytest.mark.asyncio
async def test_real_redis_progress_notification() -> None:
    url = os.getenv("MARKETPULSE_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set MARKETPULSE_TEST_REDIS_URL to a dedicated test Redis")
    from redis.asyncio import Redis

    run_id = f"test_{uuid.uuid4().hex}"
    client = Redis.from_url(url)
    notifier = ProgressNotifier(url)
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(f"marketpulse:runs:{run_id}")
        await pubsub.get_message(timeout=2)  # wait for subscription acknowledgement
        await notifier.publish(
            BlackboardEvent(
                run_id=run_id,
                version=1,
                actor="report",
                event="run.completed",
                phase="completed",
            )
        )
        async with asyncio.timeout(5):
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
                if message:
                    assert BlackboardEvent.model_validate_json(message["data"]).run_id == run_id
                    break
    finally:
        await pubsub.aclose()
        await notifier.aclose()
        await client.aclose()
