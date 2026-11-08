"""Stage 19d: the share server is loopback by default and LAN only by explicit opt-in."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from liveclip.customer_delivery_settings import ShareSettings
from liveclip.share_server import main


def test_loopback_default_builds_local_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HOST", "PORT", "ALLOW_LAN", "BASE_URL"):
        monkeypatch.delenv(f"LIVECLIP_SHARE_{name}", raising=False)
    settings = ShareSettings()
    assert (settings.host, settings.port, settings.allow_lan) == ("127.0.0.1", 8766, False)
    assert settings.share_url("tok") == "http://127.0.0.1:8766/s/tok"


@pytest.mark.parametrize(
    "values",
    [
        {"host": "0.0.0.0"},
        {"host": "192.168.1.20"},
        {"host": "192.168.1.20", "allow_lan": True},
        {"host": "0.0.0.0", "allow_lan": True, "base_url": "http://8.8.8.8:8766"},
        {"host": "0.0.0.0", "allow_lan": True, "base_url": "https://share.example.com"},
        {"host": "0.0.0.0", "allow_lan": True, "base_url": "http://192.168.1.20:8766/share"},
        {"host": "0.0.0.0", "allow_lan": True, "base_url": "http://192.168.1.20:8766/?x=1"},
        {"host": "0.0.0.0", "allow_lan": True, "base_url": "ftp://192.168.1.20"},
        {"host": "0.0.0.0", "allow_lan": True, "base_url": "http://user:pw@192.168.1.20"},
        {"base_url": "http://192.168.1.20:8766"},
        {"host": "0.0.0.0", "allow_lan": True, "base_url": "http://0.0.0.0:8766"},
    ],
)
def test_unsafe_or_incomplete_configurations_are_refused(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ShareSettings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "base_url",
    [
        "http://192.168.1.20:8766",
        "http://10.0.0.5:8766/",
        "http://172.20.1.2:9000",
        "http://169.254.10.10:8766",
        "http://studio-mac.local:8766",
        "http://[fd12::1]:8766",
    ],
)
def test_lan_opt_in_with_a_private_base_url_is_accepted(base_url: str) -> None:
    settings = ShareSettings(host="0.0.0.0", allow_lan=True, base_url=base_url)
    assert settings.share_url("tok") == f"{base_url.rstrip('/')}/s/tok"


def test_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVECLIP_SHARE_HOST", "0.0.0.0")
    monkeypatch.setenv("LIVECLIP_SHARE_ALLOW_LAN", "true")
    monkeypatch.setenv("LIVECLIP_SHARE_BASE_URL", "http://192.168.31.8:8766")
    assert ShareSettings().share_url("abc") == "http://192.168.31.8:8766/s/abc"


def test_share_server_refuses_to_start_when_misconfigured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LIVECLIP_SHARE_HOST", "0.0.0.0")
    monkeypatch.delenv("LIVECLIP_SHARE_ALLOW_LAN", raising=False)
    monkeypatch.delenv("LIVECLIP_SHARE_BASE_URL", raising=False)
    assert main() == 2
    assert "LIVECLIP_SHARE_ALLOW_LAN=true" in capsys.readouterr().err
