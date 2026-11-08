"""Expiring, revocable read-only share links for customer deliveries (Stage 19d).

A share link is scoped to one immutable, successfully built customer
delivery. The raw token (``secrets.token_urlsafe(32)``) is returned exactly
once at creation; only its SHA-256 is stored. Resolution of an unknown,
expired or revoked token is indistinguishable to the caller (``None``).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

SHARE_LINK_DEFAULT_DAYS = 7
SHARE_LINK_MAX_DAYS = 30
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]{16,128}")
ShareLinkStatus = Literal["active", "expired", "revoked"]
ShareAccessKind = Literal["viewed", "downloaded"]


class ShareLinkConflict(RuntimeError):
    """The share link cannot be created or revoked in the current state (409)."""


class ShareLinkNotFound(LookupError):
    """The share link or delivery does not exist in this project (404)."""


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def is_token_shaped(token: str) -> bool:
    return bool(_TOKEN_SHAPE.fullmatch(token))


class ShareLinkSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    link_id: str
    delivery_id: str
    project_id: str
    delivery_version: str
    created_by: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revoked_by: str | None
    status: ShareLinkStatus
    view_count: int
    download_count: int
    last_accessed_at: datetime | None


class CreatedShareLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    link: ShareLinkSnapshot
    url: str


@dataclass(frozen=True, slots=True)
class ShareTarget:
    """What an active token may reach: one built delivery and its clips."""

    link_id: str
    delivery_id: str
    project_id: str
    expires_at: datetime
    manifest_asset_id: str
    zip_asset_id: str
    title: str
    delivery_version: str
    clip_assets: dict[int, tuple[str, str, str]]  # ordinal -> (video, subtitle, title)


class ShareLinkRepository(Protocol):
    def create_link(
        self,
        *,
        project_id: str,
        delivery_id: str,
        acting_user_id: str,
        token_sha256: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> ShareLinkSnapshot: ...

    def list_links(
        self, *, project_id: str, delivery_id: str, now: datetime
    ) -> tuple[ShareLinkSnapshot, ...]: ...

    def revoke_link(
        self, *, project_id: str, link_id: str, acting_user_id: str, now: datetime
    ) -> ShareLinkSnapshot: ...

    def resolve(self, *, token_sha256: str, now: datetime) -> ShareTarget | None: ...

    def record_access(
        self, *, target: ShareTarget, kind: ShareAccessKind, detail: str, now: datetime
    ) -> None: ...


class ShareLinkService:
    def __init__(
        self,
        repository: ShareLinkRepository,
        *,
        share_url: Callable[[str], str],
        now: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._share_url = share_url
        self._now = now or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    def create(
        self,
        *,
        project_id: str,
        delivery_id: str,
        acting_user_id: str,
        expires_in_days: int = SHARE_LINK_DEFAULT_DAYS,
    ) -> CreatedShareLink:
        if not 1 <= expires_in_days <= SHARE_LINK_MAX_DAYS:
            raise ValueError(f"share links expire after 1-{SHARE_LINK_MAX_DAYS} days")
        token = self._token_factory()
        if not is_token_shaped(token):  # pragma: no cover - token_urlsafe(32) is 43 chars
            raise RuntimeError("generated share token has an unexpected shape")
        now = self._now()
        link = self._repository.create_link(
            project_id=project_id,
            delivery_id=delivery_id,
            acting_user_id=acting_user_id,
            token_sha256=token_digest(token),
            created_at=now,
            expires_at=now + timedelta(days=expires_in_days),
        )
        return CreatedShareLink(link=link, url=self._share_url(token))

    def list(self, *, project_id: str, delivery_id: str) -> tuple[ShareLinkSnapshot, ...]:
        return self._repository.list_links(
            project_id=project_id, delivery_id=delivery_id, now=self._now()
        )

    def revoke(self, *, project_id: str, link_id: str, acting_user_id: str) -> ShareLinkSnapshot:
        return self._repository.revoke_link(
            project_id=project_id, link_id=link_id, acting_user_id=acting_user_id, now=self._now()
        )

    def resolve(self, token: str) -> ShareTarget | None:
        if not is_token_shaped(token):
            return None
        return self._repository.resolve(token_sha256=token_digest(token), now=self._now())

    def record_access(self, target: ShareTarget, kind: ShareAccessKind, detail: str) -> None:
        self._repository.record_access(target=target, kind=kind, detail=detail, now=self._now())


__all__ = [
    "SHARE_LINK_DEFAULT_DAYS",
    "SHARE_LINK_MAX_DAYS",
    "CreatedShareLink",
    "ShareAccessKind",
    "ShareLinkConflict",
    "ShareLinkNotFound",
    "ShareLinkRepository",
    "ShareLinkService",
    "ShareLinkSnapshot",
    "ShareTarget",
    "is_token_shaped",
    "token_digest",
]
