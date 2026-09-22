"""Configured reviewer authentication for Phase 5 human review.

V1 has exactly one server-configured reviewer sourced from ``Settings``.
Passwords are verified with Argon2id only. The database never stores a copy
of the password hash — only the domain-separated
``reviewer_config_fingerprint`` HMAC derived from the reviewer ID and the
password hash.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from marketpulse.config import Settings

REVIEWER_CONFIG_FINGERPRINT_DOMAIN = "phase5-reviewer-config-v1"
GENERIC_AUTH_FAILURE_MESSAGE = "Invalid reviewer credentials."
ARGON2ID_HASH_PREFIX = "$argon2id$"


class ReviewerConfigurationError(ValueError):
    """Raised when the reviewer configuration is missing or not Argon2id."""


def reviewer_config_fingerprint(reviewer_id: str, password_hash: str) -> str:
    """Domain-separated HMAC-SHA256 over reviewer ID and password hash.

    Only this fingerprint may be persisted; the password hash itself is never
    copied into the database.
    """
    mac = hmac.new(REVIEWER_CONFIG_FINGERPRINT_DOMAIN.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(reviewer_id.encode("utf-8"))
    mac.update(b"\x00")
    mac.update(password_hash.encode("utf-8"))
    return mac.hexdigest()


@dataclass(frozen=True)
class ConfiguredReviewer:
    """The single configured reviewer with its derived config fingerprint."""

    reviewer_id: str
    display_name: str
    password_hash: str
    config_fingerprint: str

    @classmethod
    def from_settings(cls, settings: Settings) -> ConfiguredReviewer:
        reviewer_id = settings.reviewer_id
        password_hash = (
            settings.reviewer_password_hash.get_secret_value()
            if settings.reviewer_password_hash is not None
            else None
        )
        if not reviewer_id or not password_hash:
            raise ReviewerConfigurationError(
                "REVIEWER_ID and REVIEWER_PASSWORD_HASH must be configured"
            )
        if not password_hash.startswith(ARGON2ID_HASH_PREFIX):
            raise ReviewerConfigurationError("REVIEWER_PASSWORD_HASH must be an Argon2id hash")
        return cls(
            reviewer_id=reviewer_id,
            display_name=settings.reviewer_display_name or reviewer_id,
            password_hash=password_hash,
            config_fingerprint=reviewer_config_fingerprint(reviewer_id, password_hash),
        )


class ConfiguredReviewerAuthenticator:
    """Verifies candidate passwords against the configured Argon2id hash.

    Failures are indistinguishable to callers: ``None`` is returned for wrong
    passwords and for malformed stored hashes alike.
    """

    def __init__(self, reviewer: ConfiguredReviewer) -> None:
        self._reviewer = reviewer
        self._hasher = PasswordHasher()

    @property
    def reviewer(self) -> ConfiguredReviewer:
        return self._reviewer

    def authenticate(self, password: str) -> ConfiguredReviewer | None:
        try:
            self._hasher.verify(self._reviewer.password_hash, password)
        except (Argon2Error, ValueError):
            return None
        return self._reviewer
