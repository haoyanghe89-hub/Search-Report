import pytest

from marketpulse.domain.collaboration import BlackboardEvent
from marketpulse.services.notifications import ProgressNotifier


@pytest.mark.asyncio
async def test_redis_failure_does_not_fail_run_or_leak_credentials(caplog: object) -> None:
    class BrokenClient:
        async def publish(self, *args: object) -> None:
            raise ConnectionError("redis://private-user:fake-password@internal")

    notifier = ProgressNotifier()
    notifier.client = BrokenClient()
    await notifier.publish(
        BlackboardEvent(
            run_id="r1",
            version=1,
            actor="master",
            event="plan.completed",
            phase="plan",
        )
    )
    assert "fake-password" not in caplog.text  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_notification_is_metadata_only() -> None:
    messages: list[tuple[str, str]] = []

    class Recorder:
        async def publish(self, channel: str, payload: str) -> None:
            messages.append((channel, payload))

    notifier = ProgressNotifier()
    notifier.client = Recorder()
    await notifier.publish(
        BlackboardEvent(
            run_id="r1",
            version=1,
            actor="search",
            event="search.evidence_ready",
            phase="extract",
        )
    )
    assert messages[0][0] == "marketpulse:runs:r1"
    assert '"version":1' in messages[0][1]
    assert "evidence" not in messages[0][1].replace("search.evidence_ready", "")
