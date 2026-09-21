from __future__ import annotations

from enum import StrEnum

from marketpulse.investigation.domain.enums import RunStatus, WorkflowPhase


class Route(StrEnum):
    PLAN = "PLAN"
    COLLECT = "COLLECT"
    ANALYZE = "ANALYZE"
    VERIFY = "VERIFY"
    READY_FOR_REPORT = "READY_FOR_REPORT"


_ALLOWED: dict[WorkflowPhase, frozenset[Route]] = {
    WorkflowPhase.CREATED: frozenset({Route.PLAN}),
    WorkflowPhase.PLAN: frozenset({Route.COLLECT}),
    WorkflowPhase.COLLECT: frozenset({Route.ANALYZE}),
    WorkflowPhase.ANALYZE: frozenset({Route.VERIFY}),
    WorkflowPhase.VERIFY: frozenset({Route.COLLECT, Route.ANALYZE, Route.READY_FOR_REPORT}),
}


def require_route(current: WorkflowPhase, target: Route) -> None:
    if target not in _ALLOWED.get(current, frozenset()):
        raise ValueError(f"illegal workflow route: {current.value} -> {target.value}")


def phase_for(route: Route) -> WorkflowPhase:
    if route is Route.READY_FOR_REPORT:
        return WorkflowPhase.REPORT
    return WorkflowPhase(route.value)


def status_for(route: Route) -> RunStatus:
    if route is Route.VERIFY:
        return RunStatus.VERIFYING
    if route is Route.READY_FOR_REPORT:
        return RunStatus.READY_FOR_REPORT
    return RunStatus.RUNNING
