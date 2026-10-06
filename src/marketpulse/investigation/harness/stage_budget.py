"""Conservative call-boundary admission; validation quality gates are separate."""

from dataclasses import dataclass
from math import ceil

from marketpulse.investigation.domain.runtime import RunBudget
from marketpulse.investigation.ports.external import ModelRequest
from marketpulse.investigation.recording.canonical import canonical_request


@dataclass(frozen=True)
class StageBudgetPolicy:
    verify_tokens: float = 0.25
    report_tokens: float = 0.02
    verify_calls: float = 0.15
    report_calls: float = 0.01

    def __post_init__(self) -> None:
        for verify, report in (
            (self.verify_tokens, self.report_tokens),
            (self.verify_calls, self.report_calls),
        ):
            if min(verify, report) < 0 or verify + report >= 1:
                raise ValueError("invalid stage reserve fractions")

    def admits(self, budget: RunBudget, role: str, cost: int, *, inflight: int = 0) -> bool:
        # Report generation currently uses a local deterministic writer. Retain a small
        # explicit floor so future structured drafting cannot eat verification's share.
        verify = role.startswith("verifier")
        report = role.startswith("writer")
        token_fraction = 0 if report else self.report_tokens + (0 if verify else self.verify_tokens)
        call_fraction = 0 if report else self.report_calls + (0 if verify else self.verify_calls)
        return budget.tokens_used + inflight + cost <= budget.max_tokens - ceil(
            budget.max_tokens * token_fraction
        ) and budget.model_calls_used < budget.max_model_calls - ceil(
            budget.max_model_calls * call_fraction
        )


def conservative_request_tokens(request: ModelRequest) -> int:
    # UTF-8 bytes bound rather than optimistic chars/4: includes structured schema,
    # escaped IDs and multilingual text. Actual provider usage is still charged.
    return len(canonical_request("model.generate", request)) + (request.max_output_tokens or 0)


@dataclass(frozen=True)
class VerificationBudgetPolicy:
    max_calls: int
    max_tokens: int

    def admits(
        self,
        *,
        calls: int,
        tokens: int,
        cost: int,
        inflight_calls: int = 0,
        inflight_tokens: int = 0,
    ) -> bool:
        return (
            calls + inflight_calls < self.max_calls
            and tokens + inflight_tokens + cost <= self.max_tokens
        )
