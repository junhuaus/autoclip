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

from pydantic import Field, ValidationError, model_validator
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


# The only networks a share server may bind to or answer (Stage 19d review P1):
# loopback, RFC 1918 private IPv4, IPv4 link-local, IPv6 unique-local and IPv6
# link-local. Everything else (public IPv4/IPv6, CGNAT, multicast, the
# unspecified IPv6 address) is refused; internet exposure is out of scope.
LAN_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)
_LOOPBACK_NETWORKS = (ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128"))


def _parse_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    candidate = value.strip()
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    candidate = candidate.split("%", 1)[0]  # drop an IPv6 zone index (fe80::1%en0)
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def is_lan_address(value: str | None) -> bool:
    """True only for an IP literal inside ``LAN_NETWORKS`` (IPv4-mapped IPv6 unwrapped)."""

    if not value:
        return False
    address = _parse_address(value)
    return address is not None and any(address in network for network in LAN_NETWORKS)


def _is_loopback(host: str) -> bool:
    address = _parse_address(host)
    return address is not None and any(address in network for network in _LOOPBACK_NETWORKS)


def _is_lan_host(host: str) -> bool:
    """A LAN IP literal, or an mDNS ``.local`` name (base URL only)."""

    if host.lower().endswith(".local") and len(host) > len(".local"):
        return True
    return is_lan_address(host)


def _validate_bind_host(host: str) -> None:
    address = _parse_address(host)
    if address is None:
        raise ShareSettingsError(
            "LIVECLIP_SHARE_HOST must be an IP address literal (for example 127.0.0.1 or "
            "the Mac's LAN address from `ipconfig getifaddr en0`); hostnames are refused"
        )
    if str(address) == "0.0.0.0":
        return
    if not any(address in network for network in LAN_NETWORKS):
        raise ShareSettingsError(
            "LIVECLIP_SHARE_HOST must be loopback, 0.0.0.0, a private (10/8, 172.16/12, "
            "192.168/16) or link-local address, or an IPv6 unique-local/link-local address; "
            "public addresses and '::' are refused"
        )


class ShareSettings(BaseSettings):
    """The separate read-only share server (Stage 19d).

    - ``LIVECLIP_SHARE_HOST`` (default ``127.0.0.1``) and ``LIVECLIP_SHARE_PORT``
      (default ``8766``): where ``make share`` binds.
    - ``LIVECLIP_SHARE_HOST`` must be an IP literal: loopback, ``0.0.0.0``, a
      private/link-local IPv4 or a unique-local/link-local IPv6 address
      (prefer the Mac's own LAN address); hostnames, ``::`` and public
      addresses are refused. A non-loopback bind requires
      ``LIVECLIP_SHARE_ALLOW_LAN=true`` **and** ``LIVECLIP_SHARE_BASE_URL``.
    - Independently of the bind, the share app answers only clients whose
      address is in ``LAN_NETWORKS``; every other client gets the generic 404.
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
        _validate_bind_host(self.host)
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
            if "#" in self.base_url or "?" in self.base_url:
                raise ShareSettingsError("LIVECLIP_SHARE_BASE_URL must not contain '?' or '#'")
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
        address = _parse_address(self.host)
        host = f"[{address}]" if isinstance(address, ipaddress.IPv6Address) else self.host
        return f"http://{host}:{self.port}"

    def share_url(self, token: str) -> str:
        return f"{self.public_base_url}/s/{token}"


def share_settings_error_message(error: ValidationError) -> str:
    """One clean line describing why ``LIVECLIP_SHARE_*`` settings were refused."""

    messages = []
    for item in error.errors():
        message = str(item.get("msg", "invalid share setting"))
        messages.append(message.removeprefix("Value error, "))
    return "; ".join(messages) or "invalid LIVECLIP_SHARE_* settings"


__all__ = [
    "LAN_NETWORKS",
    "DualProfileImportSettings",
    "ShareSettings",
    "ShareSettingsError",
    "is_lan_address",
    "share_settings_error_message",
]
