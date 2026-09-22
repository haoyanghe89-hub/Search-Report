from __future__ import annotations

import hashlib
import json
from typing import TypeVar

from pydantic import BaseModel

from marketpulse.investigation.agents.contracts import (
    AgentContract,
    AnalysisInput,
    AnalysisProposal,
    ClaimDecompositionInput,
    ClaimDecompositionProposal,
    PlanInput,
    PlanProposal,
    ResearchInput,
    ResearchProposal,
    RouteInput,
    RouteProposal,
    VerificationInput,
    VerificationProposal,
    validate_agent_proposal,
)
from marketpulse.investigation.agents.prompts import (
    ANALYST_SYSTEM,
    PLANNER_SYSTEM,
    PROMPT_VERSION,
    RESEARCHER_SYSTEM,
    VERIFIER_SYSTEM,
)
from marketpulse.investigation.ports.external import ModelMessage, ModelPort, ModelRequest
from marketpulse.investigation.recording.errors import InvalidProviderResponseError

InputT = TypeVar("InputT", bound=AgentContract)
OutputT = TypeVar("OutputT", bound=AgentContract)


def context_fingerprint(value: BaseModel) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class StructuredAgent:
    def __init__(
        self,
        model: ModelPort,
        *,
        config_version: str = "phase43-agent-config-v1",
        max_output_tokens: int = 4000,
        repair_attempts: int = 1,
    ) -> None:
        if repair_attempts < 0 or repair_attempts > 2:
            raise ValueError("repair_attempts must be between zero and two")
        self._model = model
        self._config_version = config_version
        self._max_output_tokens = max_output_tokens
        self._repair_attempts = repair_attempts

    async def _generate(
        self,
        *,
        role: str,
        system: str,
        request: InputT,
        response_model: type[OutputT],
    ) -> OutputT:
        fingerprint = context_fingerprint(request)
        user_content = json.dumps(
            {
                "context_fingerprint": fingerprint,
                "bounded_context": request.model_dump(mode="json"),
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        last_error: Exception | None = None
        for attempt in range(self._repair_attempts + 1):
            messages = [
                ModelMessage(role="system", content=system),
                ModelMessage(role="user", content=user_content),
            ]
            if attempt:
                messages.append(
                    ModelMessage(
                        role="user",
                        content=(
                            "SCHEMA_REPAIR: the prior response was invalid. Return only one JSON "
                            "object matching the response schema; do not add fields."
                        ),
                    )
                )
            model_request = ModelRequest[OutputT](
                messages=tuple(messages),
                response_model=response_model,
                response_schema_version=f"{response_model.__name__}-v2",
                prompt_version=f"{PROMPT_VERSION}:{role}",
                config_version=self._config_version,
                temperature=0.0,
                max_output_tokens=self._max_output_tokens,
            )
            try:
                result = await self._model.generate(model_request)
                proposal = response_model.model_validate(result.output)
                validate_agent_proposal(request, proposal)
                return proposal
            except (InvalidProviderResponseError, ValueError) as error:
                last_error = error
        assert last_error is not None
        raise last_error


class ModelPlannerAgent(StructuredAgent):
    async def plan(self, request: PlanInput) -> PlanProposal:
        return await self._generate(
            role="planner.plan",
            system=PLANNER_SYSTEM,
            request=request,
            response_model=PlanProposal,
        )

    async def route(self, request: RouteInput) -> RouteProposal:
        return await self._generate(
            role="planner.route",
            system=PLANNER_SYSTEM,
            request=request,
            response_model=RouteProposal,
        )


class ModelResearcherAgent(StructuredAgent):
    async def research(self, request: ResearchInput) -> ResearchProposal:
        return await self._generate(
            role="researcher.research",
            system=RESEARCHER_SYSTEM,
            request=request,
            response_model=ResearchProposal,
        )


class ModelAnalystAgent(StructuredAgent):
    async def analyze(self, request: AnalysisInput) -> AnalysisProposal:
        return await self._generate(
            role="analyst.analyze",
            system=ANALYST_SYSTEM,
            request=request,
            response_model=AnalysisProposal,
        )

    async def decompose(self, request: ClaimDecompositionInput) -> ClaimDecompositionProposal:
        return await self._generate(
            role="analyst.decompose",
            system=ANALYST_SYSTEM,
            request=request,
            response_model=ClaimDecompositionProposal,
        )


class ModelVerifierAgent(StructuredAgent):
    async def verify(self, request: VerificationInput) -> VerificationProposal:
        return await self._generate(
            role="verifier.verify",
            system=VERIFIER_SYSTEM,
            request=request,
            response_model=VerificationProposal,
        )
