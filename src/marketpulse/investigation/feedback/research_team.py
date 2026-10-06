"""Complementary research agents; their proposals do not change evidence verdicts."""

from __future__ import annotations

from collections.abc import Callable
from itertools import zip_longest

from marketpulse.investigation.agents.contracts import QueryIntent, ResearchInput, ResearchProposal
from marketpulse.investigation.agents.model_agents import ModelResearcherAgent
from marketpulse.investigation.feedback.guards import ProposalGuardError, normalize_query
from marketpulse.investigation.feedback.parallel import bounded_map
from marketpulse.investigation.harness.model_call_journal import ModelCallOutcomeUnknownError
from marketpulse.investigation.harness.persistence import RunBudgetExceededError
from marketpulse.investigation.ports.external import ModelPort

SPECIALISTS = (
    (
        "official",
        "Seek primary documents, official investigations, "
        "original announcements and dated updates.",
    ),
    (
        "independent",
        "Seek independent reporting, local reporting, witness accounts "
        "and different source families.",
    ),
    (
        "technical",
        "Seek technical analyses, research papers, datasets and mechanisms; "
        "distinguish hypotheses from measurements.",
    ),
    (
        "counterevidence",
        "Actively seek contradictory evidence, corrections, disputed numbers "
        "and alternative explanations.",
    ),
)


async def research_team(
    request: ResearchInput,
    port: Callable[[str], ModelPort],
    *,
    workers: int,
    max_queries: int,
    progress: Callable[[str, str], None] | None = None,
) -> tuple[ResearchProposal, tuple[str, ...]]:
    count = min(
        workers,
        len(SPECIALISTS),
        request.remaining_search_calls,
        max(1, request.budget.model_calls_remaining // 2),
    )

    async def propose(
        specialist: tuple[str, str],
    ) -> tuple[str, ResearchProposal | None, str | None]:
        name, mandate = specialist
        task = request.task.model_copy(
            update={
                "objective": request.task.objective
                + "\nResearch perspective: "
                + mandate
                + " Use original-language and English queries where useful; avoid repeats. "
                "Return at most " + str(max_queries) + " queries."
            }
        )
        context = request.model_copy(
            update={
                "task": task,
                "remaining_search_calls": min(max_queries, request.remaining_search_calls),
            }
        )
        if progress:
            progress(name, "RUNNING")
        try:
            result = await ModelResearcherAgent(port("researcher." + name)).research(context)
            if progress:
                progress(name, "COMPLETED")
            return name, result, None
        except (RunBudgetExceededError, ModelCallOutcomeUnknownError) as error:
            if progress:
                progress(name, error.code)
            raise
        except Exception as error:
            if progress:
                progress(name, "FAILED")
            # Each failed provider call is already recorded; other perspectives may proceed.
            return name, None, type(error).__name__

    results = await bounded_map(SPECIALISTS[:count], propose, max(1, count))
    queries: list[QueryIntent] = []
    seen: set[str] = set()
    proposals = [(name, proposal) for name, proposal, _ in results if proposal is not None]
    for row in zip_longest(*(proposal.queries for _, proposal in proposals)):
        for (name, _), query in zip(proposals, row, strict=True):
            if query is None or normalize_query(query.query) in seen:
                continue
            if len(queries) >= request.remaining_search_calls:
                break
            seen.add(normalize_query(query.query))
            queries.append(query.model_copy(update={"query_key": name + ":" + query.query_key}))
    if not queries:
        raise ProposalGuardError("All research specialists failed or returned no usable queries")
    return ResearchProposal(queries=tuple(queries)), tuple(
        name + ":" + error for name, _, error in results if error is not None
    )
