"""FastAPI router for Phase 5 reviewer authentication and human review.

The router is deliberately self-contained: the mounting application supplies
``app.state.settings`` (``marketpulse.config.Settings``) and
``app.state.review_session_factory`` (a SQLAlchemy ``sessionmaker``); an
optional ``app.state.review_clock`` overrides time for tests. Reviewer
identity is always injected from the server-side session — client-supplied
reviewer identifiers are never accepted.

Security posture: JSON-only mutations, exact Origin allowlisting, a custom
CSRF header, an HttpOnly SameSite=Strict session cookie (Secure unless the
explicit loopback-only demo flag allows otherwise), keyed-HMAC client
fingerprints for rate limiting, and generic failure responses.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.config import Settings
from marketpulse.investigation.domain.enums import ReviewDecisionType
from marketpulse.investigation.review.auth import (
    GENERIC_AUTH_FAILURE_MESSAGE,
    ConfiguredReviewer,
    ConfiguredReviewerAuthenticator,
    ReviewerConfigurationError,
)
from marketpulse.investigation.review.service import (
    ReportReviewService,
    ReviewCycleNotOpenError,
    ReviewerIdentity,
    ReviewError,
    ReviewHardGateBlockedError,
    ReviewIdempotencyConflictError,
    ReviewOutcome,
    ReviewReportNotFoundError,
    StaleReviewBindingError,
)
from marketpulse.investigation.review.sessions import (
    ReviewerSessionService,
    SessionPrincipal,
    client_fingerprint,
)

SESSION_COOKIE_NAME = "mp_review"
CSRF_HEADER_NAME = "x-requested-with"
CSRF_HEADER_VALUE = "XMLHttpRequest"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testserver"})

router = APIRouter(prefix="/api/review", tags=["review"])


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class DecisionBody(BaseModel):
    report_id: str = Field(min_length=1, max_length=128)
    decision: ReviewDecisionType
    reason: str = Field(min_length=1, max_length=2000)


class ReviewerPublicInfo(BaseModel):
    reviewer_id: str
    display_name: str


class LoginResponse(BaseModel):
    reviewer: ReviewerPublicInfo
    expires_at: datetime


def _settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="review is not configured"
        )
    return settings


def _session_factory(request: Request) -> sessionmaker[Session]:
    factory = getattr(request.app.state, "review_session_factory", None)
    if not isinstance(factory, sessionmaker):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="review is not configured"
        )
        # pragma: no cover
    return cast(sessionmaker[Session], factory)


def _clock(request: Request) -> Callable[[], datetime]:
    clock = getattr(request.app.state, "review_clock", None)
    if callable(clock):
        return cast(Callable[[], datetime], clock)
    return lambda: datetime.now(UTC)


def _configured_reviewer(settings: Settings) -> ConfiguredReviewer:
    try:
        return ConfiguredReviewer.from_settings(settings)
    except ReviewerConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="review is not configured"
        ) from None


def _fingerprint_secret(settings: Settings) -> str:
    secret = settings.review_rate_limit_fingerprint_secret
    if secret is None or not secret.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="review is not configured"
        )
    return secret.get_secret_value()


def _throttle(
    settings: Settings,
    sessions: sessionmaker[Session],
    clock: Callable[[], datetime],
) -> ReviewerSessionService:
    return ReviewerSessionService(
        sessions,
        session_ttl=timedelta(hours=settings.review_session_ttl_hours),
        max_failures=settings.review_rate_limit_max_failures,
        rate_window=timedelta(minutes=settings.review_rate_limit_window_minutes),
        now=clock,
    )


def _enforce_mutation_guards(request: Request, settings: Settings) -> None:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("application/json"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="expected JSON body"
        )
    if request.headers.get(CSRF_HEADER_NAME) != CSRF_HEADER_VALUE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing CSRF header")
    origin = request.headers.get("origin")
    if origin is None or origin not in settings.review_allowed_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="origin not allowed")


def _client_host(request: Request) -> str:
    client = request.client
    return client.host if client is not None else "unknown"


def _check_transport(request: Request, settings: Settings) -> bool:
    """Return the cookie Secure flag; refuse non-loopback plain HTTP."""
    if request.url.scheme == "https":
        return True
    host = request.url.hostname or ""
    if settings.review_allow_insecure_loopback and host in LOOPBACK_HOSTS:
        return False
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="secure transport required")


def _set_session_cookie(
    request: Request, response: Response, settings: Settings, token: str, expires_at: datetime
) -> None:
    secure = _check_transport(request, settings)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        expires=expires_at,
        httponly=True,
        samesite="strict",
        path="/",
        secure=secure,
    )


def _principal(
    request: Request,
    settings: Settings,
    sessions: sessionmaker[Session],
    clock: Callable[[], datetime],
) -> SessionPrincipal:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_AUTH_FAILURE_MESSAGE
        )
    principal = _throttle(settings, sessions, clock).authenticate(token)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_AUTH_FAILURE_MESSAGE
        )
    reviewer = _configured_reviewer(settings)
    if (
        principal.reviewer_id != reviewer.reviewer_id
        or principal.reviewer_config_fingerprint != reviewer.config_fingerprint
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_AUTH_FAILURE_MESSAGE
        )
    return principal


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(_settings)],
    sessions: Annotated[sessionmaker[Session], Depends(_session_factory)],
    clock: Annotated[Callable[[], datetime], Depends(_clock)],
) -> LoginResponse:
    _enforce_mutation_guards(request, settings)
    _check_transport(request, settings)
    reviewer = _configured_reviewer(settings)
    throttle = _throttle(settings, sessions, clock)
    fingerprint = client_fingerprint(_fingerprint_secret(settings), _client_host(request))
    if throttle.is_locked(fingerprint):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_AUTH_FAILURE_MESSAGE
        )
    authenticated = ConfiguredReviewerAuthenticator(reviewer).authenticate(body.password)
    if authenticated is None:
        throttle.register_failure(fingerprint)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_AUTH_FAILURE_MESSAGE
        )
    throttle.register_success(fingerprint)
    issued = throttle.login(authenticated)
    _set_session_cookie(request, response, settings, issued.token, issued.session.expires_at)
    return LoginResponse(
        reviewer=ReviewerPublicInfo(
            reviewer_id=authenticated.reviewer_id, display_name=authenticated.display_name
        ),
        expires_at=issued.session.expires_at,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(_settings)],
    sessions: Annotated[sessionmaker[Session], Depends(_session_factory)],
    clock: Annotated[Callable[[], datetime], Depends(_clock)],
) -> None:
    _enforce_mutation_guards(request, settings)
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        _throttle(settings, sessions, clock).logout(token)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", httponly=True, samesite="strict")


@router.get("/me", response_model=ReviewerPublicInfo)
def me(
    request: Request,
    settings: Annotated[Settings, Depends(_settings)],
    sessions: Annotated[sessionmaker[Session], Depends(_session_factory)],
    clock: Annotated[Callable[[], datetime], Depends(_clock)],
) -> ReviewerPublicInfo:
    principal = _principal(request, settings, sessions, clock)
    reviewer = _configured_reviewer(settings)
    return ReviewerPublicInfo(reviewer_id=principal.reviewer_id, display_name=reviewer.display_name)


@router.post("/decisions", response_model=ReviewOutcome)
def record_decision(
    body: DecisionBody,
    request: Request,
    settings: Annotated[Settings, Depends(_settings)],
    sessions: Annotated[sessionmaker[Session], Depends(_session_factory)],
    clock: Annotated[Callable[[], datetime], Depends(_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ReviewOutcome:
    _enforce_mutation_guards(request, settings)
    if idempotency_key is None or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Idempotency-Key header is required"
        )
    principal = _principal(request, settings, sessions, clock)
    identity = ReviewerIdentity(
        reviewer_id=principal.reviewer_id,
        session_public_id=principal.session_public_id,
        config_fingerprint=principal.reviewer_config_fingerprint,
    )
    service = ReportReviewService(sessions)
    try:
        return service.record_decision(
            report_id=body.report_id,
            decision=body.decision,
            reason=body.reason,
            reviewer=identity,
            now=clock(),
            idempotency_key=idempotency_key,
        )
    except ReviewReportNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="report not found"
        ) from None
    except ReviewHardGateBlockedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="report is hard-gated; review impossible"
        ) from None
    except (
        StaleReviewBindingError,
        ReviewCycleNotOpenError,
        ReviewIdempotencyConflictError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"review cycle conflict: {error}"
        ) from None
    except ReviewError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"review failed: {error}"
        ) from None
