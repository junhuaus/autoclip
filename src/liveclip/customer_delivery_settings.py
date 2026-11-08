"""Settings for importing dual-profile results (Stage 19b).

Deliberately separate from ``liveclip.config.settings.Settings``: that module is
inside the frozen dual-profile benchmark closure, and its field set feeds the
benchmark Settings fingerprint. These settings are read only from process
environment variables (never from ``.env`` files).

- ``LIVECLIP_DUAL_PROFILE_IMPORT_ROOTS``: ``os.pathsep``-separated directories a
  run directory must resolve inside. Default ``<repo>/data/evaluations``, where
  ``dual-profile-eval`` runs are written.
- ``LIVECLIP_DUAL_PROFILE_TRANSCRIPT_ROOTS``: directories the transcript SRT must
  resolve inside. Default ``<repo>/data/evaluations`` and ``<repo>/input`` (the
  operator's local-only input directory, beside the source media). Repository
  code or test directories are never allowed by default; an operator who keeps a
  transcript elsewhere names that directory explicitly.

Relative paths given to the import resolve against the repository root.
Each root list is split on ``os.pathsep`` with every item stripped; an empty,
whitespace-only or separator-only value (e.g. ``":"``) falls back to the
default. Independently of these roots, the application's managed data
directory (``data/projects``) is never an import source.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_paths(value: str) -> tuple[Path, ...]:
    """Split on ``os.pathsep`` and strip each item; blank items are ignored.

    An unset, empty, whitespace-only or separator-only value (for example ``":"``)
    yields no paths, so the documented defaults apply.
    """

    return tuple(
        Path(item.strip()).expanduser() for item in value.split(os.pathsep) if item.strip()
    )


class DualProfileImportSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LIVECLIP_DUAL_PROFILE_",
        env_file=None,
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    import_roots_raw: str = Field(default="", validation_alias="LIVECLIP_DUAL_PROFILE_IMPORT_ROOTS")
    transcript_roots_raw: str = Field(
        default="", validation_alias="LIVECLIP_DUAL_PROFILE_TRANSCRIPT_ROOTS"
    )

    def import_roots(self, project_root: Path) -> tuple[Path, ...]:
        configured = _split_paths(self.import_roots_raw)
        return _absolute(configured or (project_root / "data" / "evaluations",), project_root)

    def transcript_roots(self, project_root: Path) -> tuple[Path, ...]:
        configured = _split_paths(self.transcript_roots_raw)
        defaults = (project_root / "data" / "evaluations", project_root / "input")
        return _absolute(configured or defaults, project_root)


def _absolute(paths: tuple[Path, ...], project_root: Path) -> tuple[Path, ...]:
    return tuple(path if path.is_absolute() else project_root / path for path in paths)


class ShareSettingsError(ValueError):
    """The share server configuration is unsafe or incomplete."""


_LOOPBACK_NAMES = frozenset({"localhost"})


def _is_loopback(host: str) -> bool:
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_lan_host(host: str) -> bool:
    """Private, link-local or unique-local addresses, or an mDNS ``.local`` name."""

    if host.lower().endswith(".local") and len(host) > len(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    if isinstance(address, ipaddress.IPv4Address):
        return address.is_private and not address.is_unspecified and not address.is_reserved
    return address in ipaddress.ip_network("fc00::/7") or address.is_link_local


class ShareSettings(BaseSettings):
    """The separate read-only share server (Stage 19d).

    - ``LIVECLIP_SHARE_HOST`` (default ``127.0.0.1``) and ``LIVECLIP_SHARE_PORT``
      (default ``8766``): where ``make share`` binds.
    - A non-loopback bind (for example ``0.0.0.0`` or a LAN address) requires
      ``LIVECLIP_SHARE_ALLOW_LAN=true`` **and** ``LIVECLIP_SHARE_BASE_URL``.
    - ``LIVECLIP_SHARE_BASE_URL`` (``http(s)://host[:port]``, no path, query or
      credentials) builds the URLs shown to reviewers. Its host must be
      loopback, a private/link-local/unique-local IP address or a ``.local``
      name: internet exposure is out of scope (there is no TLS; do not use the
      share link on public Wi-Fi).

    Read only from the process environment, never from ``.env`` files.
    """

    model_config = SettingsConfigDict(
        env_prefix="LIVECLIP_SHARE_",
        env_file=None,
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    port: int = Field(default=8766, ge=1, le=65_535)
    allow_lan: bool = False
    base_url: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_exposure(self) -> ShareSettings:
        if not _is_loopback(self.host):
            if not self.allow_lan:
                raise ShareSettingsError(
                    "LIVECLIP_SHARE_HOST is not loopback; set LIVECLIP_SHARE_ALLOW_LAN=true "
                    "to share on the local network"
                )
            if self.base_url is None:
                raise ShareSettingsError(
                    "LIVECLIP_SHARE_BASE_URL is required when sharing on the local network"
                )
        if self.base_url is not None:
            parsed = urlsplit(self.base_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ShareSettingsError(
                    "LIVECLIP_SHARE_BASE_URL must be http(s)://host[:port] without path or query"
                )
            try:
                parsed.port  # noqa: B018 - validates the port
            except ValueError as exc:
                raise ShareSettingsError("LIVECLIP_SHARE_BASE_URL has an invalid port") from exc
            if not _is_lan_host(parsed.hostname):
                raise ShareSettingsError(
                    "LIVECLIP_SHARE_BASE_URL must be a loopback, private-network or .local "
                    "address; internet exposure is not supported"
                )
            if not _is_loopback(parsed.hostname) and not self.allow_lan:
                raise ShareSettingsError(
                    "a LAN LIVECLIP_SHARE_BASE_URL requires LIVECLIP_SHARE_ALLOW_LAN=true"
                )
        return self

    @property
    def public_base_url(self) -> str:
        if self.base_url is not None:
            return self.base_url.rstrip("/")
        host = self.host if not self.host.startswith("::") else "[::1]"
        return f"http://{host}:{self.port}"

    def share_url(self, token: str) -> str:
        return f"{self.public_base_url}/s/{token}"


__all__ = ["DualProfileImportSettings", "ShareSettings", "ShareSettingsError"]
