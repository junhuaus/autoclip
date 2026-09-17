from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import liveclip.cli.app as cli_module
import liveclip.providers.llm.codex as codex_module
import liveclip.providers.readiness as readiness_module
from liveclip.config import Settings
from liveclip.providers.readiness import (
    ProviderNotReady,
    assess_provider_readiness,
    require_processing_ready,
)
from liveclip.providers.telemetry import ProviderConfigurationError


def test_mock_mode_is_runnable_but_explicitly_warns_that_content_is_not_real() -> None:
    readiness = assess_provider_readiness(Settings(ai_provider="mock", _env_file=None))

    assert readiness.processing_ready is True
    assert readiness.asr_provider == "mock"
    assert readiness.llm_provider == "mock"
    assert readiness.blocking_issues == ()
    assert readiness.warnings == ("MOCK_ASR_SELECTED", "MOCK_LLM_SELECTED")


def test_openai_codex_mode_requires_real_asr_and_logged_in_codex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        readiness_module,
        "assert_codex_cli_ready",
        lambda _configured: "codex-cli-editorial-v1.0.146.0",
    )
    settings = Settings(ai_provider="openai-codex", _env_file=None)

    readiness = assess_provider_readiness(settings)

    assert readiness.asr_provider == "openai"
    assert readiness.llm_provider == "codex_cli"
    assert readiness.asr_ready is False
    assert readiness.llm_ready is True
    assert readiness.processing_ready is False
    assert readiness.blocking_issues == ("OPENAI_ASR_NOT_CONFIGURED",)
    with pytest.raises(
        ProviderNotReady,
        match="Codex CLI edits transcripts but does not perform ASR",
    ):
        require_processing_ready(settings)


def test_openai_codex_mode_is_ready_with_local_key_presence_and_codex_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        readiness_module,
        "assert_codex_cli_ready",
        lambda _configured: "codex-cli-editorial-v1.0.146.0",
    )
    settings = Settings(
        ai_provider="openai-codex",
        openai_api_key="local-secret-never-returned",
        _env_file=None,
    )

    readiness = require_processing_ready(settings)

    assert readiness.processing_ready is True
    assert readiness.blocking_issues == ()
    assert "local-secret-never-returned" not in repr(readiness)


def test_openrouter_codex_requires_new_local_key_and_never_exposes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        readiness_module,
        "assert_codex_cli_ready",
        lambda _configured: "codex-cli-editorial-v2.0.146.0." + "a" * 64,
    )
    missing = assess_provider_readiness(
        Settings(ai_provider="openrouter-codex", openrouter_api_key=None, _env_file=None)
    )
    assert missing.asr_provider == "openrouter"
    assert missing.llm_provider == "codex_cli"
    assert missing.processing_ready is False
    assert missing.blocking_issues == ("OPENROUTER_ASR_NOT_CONFIGURED",)

    ready = require_processing_ready(
        Settings(
            ai_provider="openrouter-codex",
            openrouter_api_key="router-secret-never-returned",
            _env_file=None,
        )
    )
    assert ready.processing_ready is True
    assert "router-secret-never-returned" not in repr(ready)


def test_whitespace_only_openrouter_key_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        readiness_module,
        "assert_codex_cli_ready",
        lambda _configured: "codex-cli-editorial-v2.0.146.0." + "a" * 64,
    )

    readiness = assess_provider_readiness(
        Settings(
            ai_provider="openrouter-codex",
            openrouter_api_key="   ",
            _env_file=None,
        )
    )

    assert readiness.asr_ready is False
    assert readiness.blocking_issues == ("OPENROUTER_ASR_NOT_CONFIGURED",)


def test_mlx_codex_is_ready_without_cloud_key_when_model_and_codex_are_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = (tmp_path / "large-v3").resolve()
    observed: list[Path] = []
    monkeypatch.setattr(
        readiness_module,
        "assert_mlx_asr_ready",
        lambda path: observed.append(path),
    )
    monkeypatch.setattr(
        readiness_module,
        "assert_codex_cli_ready",
        lambda _configured: "codex-cli-editorial-v2.0.146.0." + "a" * 64,
    )

    readiness = require_processing_ready(
        Settings(
            ai_provider="mlx-codex",
            mlx_asr_model_path=model_path,
            openai_api_key=None,
            openrouter_api_key=None,
            _env_file=None,
        )
    )

    assert observed == [model_path]
    assert readiness.asr_provider == "mlx"
    assert readiness.llm_provider == "codex_cli"
    assert readiness.processing_ready is True
    assert readiness.blocking_issues == ()


def test_mlx_readiness_failure_is_bounded_and_does_not_expose_model_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = (tmp_path / "secret-model-location").resolve()

    def unavailable(_path: Path) -> None:
        raise ProviderConfigurationError(f"missing model at {model_path}")

    monkeypatch.setattr(readiness_module, "assert_mlx_asr_ready", unavailable)
    monkeypatch.setattr(
        readiness_module,
        "assert_codex_cli_ready",
        lambda _configured: "codex-cli-editorial-v2.0.146.0." + "a" * 64,
    )

    readiness = assess_provider_readiness(
        Settings(
            ai_provider="mlx-codex",
            mlx_asr_model_path=model_path,
            _env_file=None,
        )
    )

    assert readiness.asr_ready is False
    assert readiness.blocking_issues == ("MLX_ASR_NOT_READY",)
    assert str(model_path) not in repr(readiness)


def test_codex_probe_failure_is_safe_and_does_not_silently_select_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_configured: str) -> str:
        raise ProviderConfigurationError("raw provider detail")

    monkeypatch.setattr(readiness_module, "assert_codex_cli_ready", unavailable)
    readiness = assess_provider_readiness(Settings(ai_provider="mock-codex", _env_file=None))

    assert readiness.asr_provider == "mock"
    assert readiness.llm_provider == "codex_cli"
    assert readiness.llm_ready is False
    assert readiness.processing_ready is False
    assert readiness.blocking_issues == ("CODEX_CLI_NOT_READY",)
    assert "raw provider detail" not in repr(readiness)


def test_codex_login_probe_uses_argv_shell_false_and_secret_stripped_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-login-probe")
    monkeypatch.setattr(codex_module, "resolve_codex_executable", lambda _value: "/codex")
    monkeypatch.setattr(
        codex_module,
        "codex_cli_contract_version",
        lambda _value: "codex-cli-editorial-v1.0.146.0",
    )

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observed["argv"] = argv
        observed.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "Logged in using ChatGPT", "")

    monkeypatch.setattr(codex_module.subprocess, "run", fake_run)

    contract = codex_module.assert_codex_cli_ready("codex")

    assert contract == "codex-cli-editorial-v1.0.146.0"
    assert observed["argv"] == ["/codex", "login", "status"]
    assert observed["shell"] is False
    assert "OPENAI_API_KEY" not in observed["env"]


def test_cli_full_run_stops_before_project_creation_when_real_providers_are_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "get_settings",
        lambda: Settings(ai_provider="openai", openai_api_key=None, _env_file=None),
    )

    result = CliRunner().invoke(
        cli_module.app,
        ["run", "--input", "/private/tmp/video-that-must-not-be-opened.mp4"],
    )

    assert result.exit_code == 1
    assert "OPENAI_ASR_NOT_CONFIGURED" in result.output
    assert "Project ID" not in result.output
