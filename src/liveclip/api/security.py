from __future__ import annotations

import hashlib
import hmac
import ipaddress
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from liveclip.config import Settings


class ApiAuthenticationError(PermissionError):
    """A request did not provide valid local API authorization."""


@dataclass(frozen=True, slots=True)
class AuthenticatedCaller:
    username: str
    caller_scope: str
    user_id: str | None = None
    system_role: str = "member"
    credential_kind: str = "legacy"
    session_id: str | None = None


def validate_network_settings(settings: Settings) -> None:
    token = _configured_token(settings)
    if not _is_loopback_host(settings.api_host) and token is None:
        raise ValueError("a Bearer token is required when the API binds beyond loopback")
    for origin in settings.cors_origins:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or not _is_loopback_host(parsed.hostname)
        ):
            raise ValueError("CORS origins must be explicit loopback HTTP origins")


class ApiSecurity:
    def __init__(self, settings: Settings) -> None:
        validate_network_settings(settings)
        self._token = _configured_token(settings)
        self._default_username = settings.workspace_username
        self._workspace_tokens = settings.workspace_tokens
        self._ttl_seconds = settings.media_url_ttl_seconds

    @property
    def caller_scope(self) -> str:
        if self._token is None:
            return "local"
        digest = hashlib.sha256(self._token.encode("utf-8")).hexdigest()[:24]
        return f"bearer:{digest}"

    def authenticate(self, authorization: str | None) -> AuthenticatedCaller:
        if authorization is None and self._token is None and not self._workspace_tokens:
            return AuthenticatedCaller(username=self._default_username, caller_scope="local")
        credential = _bearer_credential(authorization)
        for username, expected in self._workspace_tokens.items():
            if hmac.compare_digest(credential, expected):
                digest = hashlib.sha256(expected.encode("utf-8")).hexdigest()[:24]
                return AuthenticatedCaller(
                    username=username,
                    caller_scope=f"workspace:{username}:{digest}",
                )
        if self._token is not None and hmac.compare_digest(credential, self._token):
            return AuthenticatedCaller(
                username=self._default_username,
                caller_scope=self.caller_scope,
            )
        raise ApiAuthenticationError("Bearer authorization is invalid")

    def require_bearer(self, authorization: str | None) -> None:
        if self._token is None:
            return
        if authorization is None:
            raise ApiAuthenticationError("Bearer authorization is required")
        scheme, separator, credential = authorization.partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not credential
            or not hmac.compare_digest(credential, self._token)
        ):
            raise ApiAuthenticationError("Bearer authorization is invalid")

    def signed_url(self, *, path: str, resource: str, now: int | None = None) -> str:
        if self._token is None:
            return path
        expires = (int(time.time()) if now is None else now) + self._ttl_seconds
        signature = self._signature(path=path, resource=resource, expires=expires)
        return f"{path}?{urlencode({'expires': expires, 'signature': signature})}"

    def authorize_resource(
        self,
        *,
        path: str,
        resource: str,
        authorization: str | None,
        expires: int | None,
        signature: str | None,
        now: int | None = None,
    ) -> None:
        if self._token is None:
            return
        current = int(time.time()) if now is None else now
        if (
            expires is not None
            and signature is not None
            and current <= expires <= current + self._ttl_seconds
            and hmac.compare_digest(
                signature,
                self._signature(path=path, resource=resource, expires=expires),
            )
        ):
            return
        self.require_bearer(authorization)

    def _signature(self, *, path: str, resource: str, expires: int) -> str:
        if self._token is None:
            raise RuntimeError("signed URLs require a configured API token")
        payload = f"liveclip-media-v1\nGET\n{path}\n{resource}\n{expires}".encode()
        return hmac.new(self._token.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _configured_token(settings: Settings) -> str | None:
    if settings.api_token is None:
        return None
    value = settings.api_token.get_secret_value()
    return value if value else None


def _bearer_credential(authorization: str | None) -> str:
    if authorization is None:
        raise ApiAuthenticationError("Bearer authorization is required")
    scheme, separator, credential = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not credential:
        raise ApiAuthenticationError("Bearer authorization is invalid")
    return credential


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False
