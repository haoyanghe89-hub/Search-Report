from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
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
        repair_attempts: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if repair_attempts < 0 or repair_attempts > 2:
            raise ValueError("repair_attempts must be between zero and two")
        self._model = model
        self._config_version = config_version
        self._max_output_tokens = max_output_tokens
        self._repair_attempts = repair_attempts
        self._sleep = sleep

    async def _generate(
        self,
        *,
        role: str,
        system: str,
        request: InputT,
        response_model: type[OutputT],
        repair_attempts: int | None = None,
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
        repair_hint = ""
        attempts = self._repair_attempts if repair_attempts is None else repair_attempts
        for attempt in range(attempts + 1):
            messages = [
                ModelMessage(role="system", content=system),
                ModelMessage(role="user", content=user_content),
            ]
            if attempt:
                await self._sleep(0.25 * 2 ** (attempt - 1))
                messages.append(
                    ModelMessage(
                        role="user",
                        content=(
                            "SCHEMA_REPAIR: the prior response was invalid. Return only one JSON "
                            "object matching the response schema; do not add fields. "
                            "Copy reference IDs exactly from the bounded context; never shorten "
                            "them. Use only schema enum values. Repair these errors: " + repair_hint
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
                max_output_tokens=(
                    min(self._max_output_tokens * 2, 16000)
                    if getattr(last_error, "code", None) == "MODEL_OUTPUT_TRUNCATED"
                    else self._max_output_tokens
                ),
            )
            try:
                result = await self._model.generate(model_request)
                proposal = response_model.model_validate(result.output)
                try:
                    validate_agent_proposal(request, proposal)
                except ValueError as error:
                    # Contract checks contain application-authored messages, not provider text.
                    raise InvalidProviderResponseError(
                        "model proposal failed reference validation",
                        validation_issues=(str(error),),
                    ) from error
                return proposal
            except (InvalidProviderResponseError, ValueError) as error:
                last_error = error
                repair_hint = "; ".join(getattr(error, "validation_issues", ())) or (
                    "Response must be a complete JSON object satisfying every required field."
                )
        assert last_error is not None
        if isinstance(last_error, InvalidProviderResponseError):
            raise last_error
        raise InvalidProviderResponseError("structured response repair exhausted") from last_error


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
    async def analyze(
        self, request: AnalysisInput, *, ground_quotes: bool = False
    ) -> AnalysisProposal:
        self.grounding_diagnostics: dict[str, str] = {}
        system = ANALYST_SYSTEM
        if ground_quotes:
            request = request.model_copy(
                update={
                    "max_candidate_evidence": min(request.max_candidate_evidence, 6),
                    "max_candidate_claims": min(request.max_candidate_claims, 4),
                }
            )
            system += (
                "\nReturn at most 6 evidence items and 4 NEW atomic claims focused on the target "
                "question. Use short verbatim quotes (at most 300 characters each), copied "
                "from one artifact excerpt. Copy that artifact's supplied locator as a "
                "placeholder INCLUDING locator.quote_hash; omit only the optional top-level "
                "EvidenceCandidate.quote_hash. The application computes exact substring "
                "offsets and SHA-256 from the source. Never paraphrase quotes. Omit optional "
                "fields when unnecessary. Do not repeat existing claims."
                "\nReference namespaces: artifact_key must be copied exactly from artifacts; "
                "source_key and snapshot_key are provenance, NOT artifact_key. Each artifact "
                "includes its actual source_key and source_title. Choose local unique E1/E2 "
                "evidence_key and C1/C2 claim_key values. supporting_evidence_keys, "
                "contradicting_evidence_keys, relations and conflict_observations may reference "
                "ONLY evidence and claims included in this response. To attach new support "
                "to an existing claim, include that claim in claims using its exact existing "
                "claim_key, statement and claim_type. Copy qualifiers.entity to entity_qualifiers, "
                "qualifiers.time to time_qualifiers and qualifiers.scope to scope_qualifiers; "
                "never emit a dangling reference."
                "\nDistinguish a company saying a product has a capability (STATEMENT, "
                "attributed to that speaker) from the capability being independently proven "
                "(QUANTITATIVE or EVENT_FACT). ATTRIBUTION is investigative responsibility, "
                "not a synonym for a product announcement. Retain benchmark names, units, "
                "dates, versions, comparison scope and uncertainty in qualifiers. Never "
                "reinterpret a claim merely to satisfy a weaker validation profile. Where "
                "the same exact existing claim has new support, reuse its claim_key and "
                "attach the new evidence rather than introducing a paraphrased duplicate."
            )
        proposal = await self._generate(
            role="analyst.analyze",
            system=system,
            request=request,
            response_model=AnalysisProposal,
        )
        if not ground_quotes:
            return proposal
        artifacts = {item.artifact_key: item for item in request.artifacts}
        grounded = []
        for candidate in proposal.evidence:
            artifact = artifacts[candidate.artifact_key]
            # HTML extraction inserts line breaks around inline tags. Match whitespace
            # flexibly, but preserve every other character and store original source text.
            # Never fuzzy-match words or join disjoint passages.
            pattern = r"\s+".join(re.escape(part) for part in re.split(r"\s+", candidate.quote))
            matches = list(re.finditer(pattern, artifact.excerpt))
            resolved = matches[0] if len(matches) == 1 else None
            if len(matches) > 1:
                positioned = [
                    match
                    for match in matches
                    if candidate.locator.locator_type == artifact.locator.locator_type
                    and getattr(candidate.locator, "page", None)
                    == getattr(artifact.locator, "page", None)
                    and candidate.locator.start == artifact.locator.start + match.start()
                    and candidate.locator.end == artifact.locator.start + match.end()
                ]
                if len(positioned) == 1:
                    resolved = positioned[0]
            self.grounding_diagnostics[candidate.evidence_key] = (
                "QUOTE_NOT_FOUND"
                if not matches
                else "QUOTE_MULTIPLE_MATCHES"
                if resolved is None
                else "QUOTE_POSITION_RESOLVED"
                if len(matches) > 1
                else "QUOTE_UNIQUE_MATCH"
            )
            if resolved is not None:
                match = resolved
                quote = match.group()
                digest = hashlib.sha256(quote.encode("utf-8")).hexdigest()
                locator = artifact.locator.model_copy(
                    update={
                        "start": artifact.locator.start + match.start(),
                        "end": artifact.locator.start + match.end(),
                        "quote_hash": digest,
                    }
                )
                candidate = candidate.model_copy(
                    update={"locator": locator, "quote_hash": digest, "quote": quote}
                )
            grounded.append(candidate)
        return proposal.model_copy(update={"evidence": tuple(grounded)})

    async def decompose(self, request: ClaimDecompositionInput) -> ClaimDecompositionProposal:
        return await self._generate(
            role="analyst.decompose",
            system=ANALYST_SYSTEM,
            request=request,
            response_model=ClaimDecompositionProposal,
            # Decomposition is nested inside extraction; preserve its small call budget.
            repair_attempts=min(self._repair_attempts, 1),
        )


class ModelVerifierAgent(StructuredAgent):
    async def verify(self, request: VerificationInput) -> VerificationProposal:
        return await self._generate(
            role="verifier.verify",
            system=VERIFIER_SYSTEM,
            request=request,
            response_model=VerificationProposal,
        )
