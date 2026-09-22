"""Server-side reviewer sessions and login throttling for Phase 5 review.

Sessions use opaque 256-bit tokens; only a domain-separated SHA-256 token
hash is persisted. TTL is fixed (not sliding). A new login revokes the
previous active session by incrementing the reviewer generation. Logout
revokes immediately. Rate-limit buckets are keyed by a keyed HMAC of the
normalized client address — raw addresses are never stored.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.investigation.persistence.models import ReviewerSessionRow
from marketpulse.investigation.reporting.persistence import ReportGovernanceRepository
from marketpulse.investigation.review.auth import ConfiguredReviewer
from marketpulse.investigation.review.models import (
    ReviewerAuthState,
    ReviewerSession,
    ReviewRateBucket,
)

SESSION_TOKEN_HASH_DOMAIN = "mp-review-session-v1"
RATE_FINGERPRINT_DOMAIN = "mp-review-rate-v1"
DEFAULT_SESSION_TTL = timedelta(hours=8)
DEFAULT_MAX_FAILURES = 5
DEFAULT_RATE_WINDOW = timedelta(minutes=15)


def hash_session_token(token: str) -> str:
    """Domain-separated SHA-256 over an opaque session token."""
    return hashlib.sha256(f"{SESSION_TOKEN_HASH_DOMAIN}:{token}".encode()).hexdigest()


def client_fingerprint(secret: str, client_address: str) -> str:
    """Keyed HMAC-SHA256 over the normalized client address.

    The raw address is never persisted; the secret is never logged, persisted,
    or returned.
    """
    normalized = client_address.strip().lower()
    mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(RATE_FINGERPRINT_DOMAIN.encode("utf-8"))
    mac.update(b"\x00")
    mac.update(normalized.encode("utf-8"))
    return mac.hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class IssuedSession:
    """Freshly issued session; the raw token exists only here."""

    token: str
    session: ReviewerSession


@dataclass(frozen=True)
class SessionPrincipal:
    """Authenticated reviewer identity injected into review mutations."""

    reviewer_id: str
    session_public_id: str
    generation: int
    reviewer_config_fingerprint: str


class ReviewerSessionService:
    """Owns reviewer session lifecycle and login rate-limit buckets."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        session_ttl: timedelta = DEFAULT_SESSION_TTL,
        max_failures: int = DEFAULT_MAX_FAILURES,
        rate_window: timedelta = DEFAULT_RATE_WINDOW,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        if max_failures < 1:
            raise ValueError("max_failures must be positive")
        self._sessions = sessions
        self._governance = ReportGovernanceRepository(sessions)
        self._session_ttl = session_ttl
        self._max_failures = max_failures
        self._rate_window = rate_window
        self._now = now

    def login(self, reviewer: ConfiguredReviewer) -> IssuedSession:
        """Create a new active session, revoking any previous active session."""
        now = self._now()
        token = secrets.token_urlsafe(32)
        with self._sessions.begin() as session:
            state = self._governance.get_auth_state_in_session(session, reviewer.reviewer_id)
            generation = (state.active_generation if state is not None else 0) + 1
            if state is not None and state.active_session_public_id is not None:
                previous = session.get(ReviewerSessionRow, state.active_session_public_id)
                if previous is not None and previous.revoked_at is None:
                    previous.revoked_at = now
            issued = ReviewerSession(
                session_public_id=f"SES-{secrets.token_hex(12)}",
                reviewer_id=reviewer.reviewer_id,
                token_hash=hash_session_token(token),
                reviewer_config_fingerprint=reviewer.config_fingerprint,
                generation=generation,
                created_at=now,
                expires_at=now + self._session_ttl,
            )
            self._governance.save_session_in_session(session, issued)
            self._governance.save_auth_state_in_session(
                session,
                ReviewerAuthState(
                    reviewer_id=reviewer.reviewer_id,
                    active_session_public_id=issued.session_public_id,
                    active_generation=generation,
                    config_fingerprint=reviewer.config_fingerprint,
                    updated_at=now,
                ),
            )
        return IssuedSession(token=token, session=issued)

    def authenticate(self, token: str) -> SessionPrincipal | None:
        """Resolve a raw session token to a principal, or ``None`` if invalid."""
        now = self._now()
        with self._sessions() as session:
            found = self._governance.session_by_token_hash_in_session(
                session, hash_session_token(token)
            )
            if found is None or found.revoked_at is not None:
                return None
            if _aware(found.expires_at) <= now:
                return None
            state = self._governance.get_auth_state_in_session(session, found.reviewer_id)
            if state is None or state.active_session_public_id != found.session_public_id:
                return None
            return SessionPrincipal(
                reviewer_id=found.reviewer_id,
                session_public_id=found.session_public_id,
                generation=found.generation,
                reviewer_config_fingerprint=found.reviewer_config_fingerprint,
            )

    def logout(self, token: str) -> None:
        """Revoke the session immediately; unknown tokens are ignored."""
        now = self._now()
        with self._sessions.begin() as session:
            found = self._governance.session_by_token_hash_in_session(
                session, hash_session_token(token)
            )
            if found is None:
                return
            row = session.get(ReviewerSessionRow, found.session_public_id)
            if row is not None and row.revoked_at is None:
                row.revoked_at = now
            state = self._governance.get_auth_state_in_session(session, found.reviewer_id)
            if state is not None and state.active_session_public_id == found.session_public_id:
                self._governance.save_auth_state_in_session(
                    session,
                    state.model_copy(update={"active_session_public_id": None, "updated_at": now}),
                )

    def purge_expired_sessions(self, *, older_than: datetime) -> int:
        """Delete expired or revoked session rows; governance history survives."""
        with self._sessions.begin() as session:
            result = session.execute(
                delete(ReviewerSessionRow).where(ReviewerSessionRow.expires_at < older_than)
            )
        return int(getattr(result, "rowcount", 0) or 0)

    # -- login throttling ------------------------------------------------------

    def is_locked(self, bucket_fingerprint: str) -> bool:
        now = self._now()
        with self._sessions() as session:
            bucket = self._governance.get_rate_bucket_in_session(session, bucket_fingerprint)
        return (
            bucket is not None
            and bucket.locked_until is not None
            and _aware(bucket.locked_until) > now
        )

    def register_failure(self, bucket_fingerprint: str) -> ReviewRateBucket:
        """Record one failed login; locks the bucket after ``max_failures``."""
        now = self._now()
        with self._sessions.begin() as session:
            bucket = self._governance.get_rate_bucket_in_session(session, bucket_fingerprint)
            if bucket is None or now - _aware(bucket.window_started_at) > self._rate_window:
                bucket = ReviewRateBucket(
                    bucket_fingerprint=bucket_fingerprint,
                    failure_count=0,
                    window_started_at=now,
                    locked_until=None,
                    updated_at=now,
                )
            failure_count = bucket.failure_count + 1
            locked_until = bucket.locked_until
            if failure_count >= self._max_failures:
                locked_until = now + self._rate_window
            updated = bucket.model_copy(
                update={
                    "failure_count": failure_count,
                    "locked_until": locked_until,
                    "updated_at": now,
                }
            )
            self._governance.save_rate_bucket_in_session(session, updated)
        return updated

    def register_success(self, bucket_fingerprint: str) -> None:
        """Reset the failure bucket after a successful login."""
        now = self._now()
        with self._sessions.begin() as session:
            bucket = self._governance.get_rate_bucket_in_session(session, bucket_fingerprint)
            if bucket is not None:
                self._governance.save_rate_bucket_in_session(
                    session,
                    bucket.model_copy(
                        update={
                            "failure_count": 0,
                            "locked_until": None,
                            "window_started_at": now,
                            "updated_at": now,
                        }
                    ),
                )
