from pathlib import Path

import pytest
from sqlalchemy import event

from marketpulse.domain.collaboration import BlackboardState
from marketpulse.services.blackboard import BlackboardStore, StaleBlackboardWrite


def state(run_id: str = "run_a") -> BlackboardState:
    return BlackboardState(run_id=run_id, topic="Market research", competitor_limit=3)


def test_persistent_isolated_state_and_version_conflicts(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path.as_posix()}/state.db"
    board = BlackboardStore(url)
    board.create(state())
    board.create(state("run_b"))
    one, stale = board.load("run_a"), board.load("run_a")
    one.warnings = ["evidence missing"]
    board.save(one, "master", "review.completed")
    with pytest.raises(StaleBlackboardWrite):
        board.save(stale, "report", "report.drafted")
    assert board.load("run_b").warnings == []
    assert [e.version for e in board.history("run_a")] == [0, 1]
    assert len(board.history("run_a", after_version=0)) == 1
    board.close()
    reopened = BlackboardStore(url)
    assert reopened.load("run_a").warnings == ["evidence missing"]
    assert reopened.load("run_a").version == 1
    reopened.close()


def test_snapshot_and_event_are_atomic() -> None:
    board = BlackboardStore("sqlite:///:memory:")
    current = state()
    board.create(current)

    def reject_event(conn: object, cursor: object, statement: str, *args: object) -> None:
        if statement.startswith("INSERT INTO mp_events"):
            raise RuntimeError("simulated event insert failure")

    event.listen(board.engine, "before_cursor_execute", reject_event)
    current.warnings.append("must not commit")
    with pytest.raises(RuntimeError, match="simulated"):
        board.save(current, "search", "search.completed")
    event.remove(board.engine, "before_cursor_execute", reject_event)
    assert board.load(current.run_id).warnings == []
    assert board.load(current.run_id).version == current.version == 0
    assert len(board.history(current.run_id)) == 1
    board.close()
