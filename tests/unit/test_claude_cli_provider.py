from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

import liveclip.cli.doctor as doctor_module
from liveclip.clipping_skills.dual_profile_v1 import load_dual_profile_prompt
from liveclip.config import Settings
from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.dual_profile import semantic_cache_key
from liveclip.providers.llm import claude_cli as claude_module
from liveclip.providers.llm import codex as codex_module
from liveclip.providers.llm import structured as structured_module
from liveclip.providers.llm.claude_cli import (
    CLAUDE_SYSTEM_PROMPT,
    SUPPORTED_CLAUDE_CLI_VERSION,
    ClaudeCliRetryPolicy,
    ClaudeCliStructuredLLMProvider,
    assert_claude_cli_ready,
    classify_claude_cli_failure,
    claude_cli_contract_version,
    claude_cli_environment,
)
from liveclip.providers.llm.structured import StructuredProviderError
from liveclip.providers.telemetry import ProviderCallStatus, ProviderConfigurationError
from liveclip.services.claude_smoke import ClaudeSmokeError, run_claude_smoke
from liveclip.services.structured_editorial_provider import (
    configured_structured_editorial_provider_factory,
)

_FAKE_CLAUDE = """#!{python}
import json, os, sys
from pathlib import Path

here = Path(__file__).resolve().parent
scenario = json.loads((here / "scenario.json").read_text())
args = sys.argv[1:]
if args == ["--version"]:
    sys.stdout.write(scenario.get("version", "{version} (Claude Code)\\n"))
    sys.exit(0)
if args[:2] == ["auth", "status"]:
    sys.stdout.write(json.dumps(scenario["auth"]))
    sys.exit(0)
log = here / "calls.jsonl"
index = len(log.read_text().splitlines()) if log.exists() else 0
stdin = sys.stdin.read()
cwd = os.getcwd()
with log.open("a") as stream:
    stream.write(json.dumps({{
        "argv": args,
        "env": dict(os.environ),
        "cwd": cwd,
        "cwd_entries": sorted(os.listdir(cwd)),
        "stdin": stdin,
    }}) + "\\n")
responses = scenario["responses"]
response = responses[min(index, len(responses) - 1)]
sys.stdout.write(json.dumps(response["stdout"]) if "stdout" in response else response["raw"])
sys.stderr.write(response.get("stderr", ""))
sys.exit(response.get("returncode", 0))
"""
_SUBSCRIPTION_AUTH = {
    "loggedIn": True,
    "authMethod": "claude.ai",
    "apiProvider": "firstParty",
    "email": "fixture-person@example.invalid",
    "orgName": "Fixture Org",
}


class Answer(BaseModel):
    value: str


def _success(structured: object, *, result_text: str = "ignored text") -> dict[str, Any]:
    return {
        "stdout": {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "api_error_status": None,
            "result": result_text,
            "structured_output": structured,
            "session_id": "00000000-0000-4000-8000-000000000000",
            "num_turns": 2,
            "duration_api_ms": 1200,
            "permission_denials": [],
            "subagent_stats": {"spawned": 0},
            "total_cost_usd": 0.5,
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 900,
                "cache_read_input_tokens": 90,
                "output_tokens": 40,
                "output_tokens_details": {"thinking_tokens": 5},
                "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
            },
            "modelUsage": {"claude-opus-5-5": {"inputTokens": 10, "outputTokens": 40}},
        }
    }


def _api_error(status: int | None, text: str) -> dict[str, Any]:
    return {
        "stdout": {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "api_error_status": status,
            "result": text,
            "structured_output": None,
            "num_turns": 1,
            "permission_denials": [],
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "modelUsage": {},
        },
        "returncode": 1,
    }


def _install_fake(
    tmp_path: Path,
    responses: list[dict[str, Any]],
    *,
    version: str | None = None,
    auth: dict[str, object] | None = None,
) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    executable = bin_dir / "claude"
    executable.write_text(
        _FAKE_CLAUDE.format(python=sys.executable, version=SUPPORTED_CLAUDE_CLI_VERSION),
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    scenario: dict[str, object] = {
        "responses": responses,
        "auth": _SUBSCRIPTION_AUTH if auth is None else auth,
    }
    if version is not None:
        scenario["version"] = version
    (bin_dir / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    return executable


def _calls(executable: Path) -> list[dict[str, Any]]:
    log = executable.parent / "calls.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def _provider(
    executable: Path,
    *,
    effort: str = "medium",
    policy: ClaudeCliRetryPolicy | None = None,
    sleeps: list[float] | None = None,
) -> ClaudeCliStructuredLLMProvider:
    recorded = sleeps if sleeps is not None else []
    return ClaudeCliStructuredLLMProvider(
        prompts=load_dual_profile_prompt("discovery", ClipProfile.SHORT_HIGHLIGHT),
        model_name="claude-opus-5-5",
        claude_executable=str(executable),
        timeout_seconds=30,
        reasoning_effort=effort,  # type: ignore[arg-type]
        retry_policy=policy
        or ClaudeCliRetryPolicy(
            max_attempts=4,
            base_delay_seconds=2.0,
            max_delay_seconds=60.0,
            total_wait_seconds=300.0,
        ),
        sleep=lambda delay, _cancel: recorded.append(delay),
        jitter=lambda: 0.5,
    )


@pytest.fixture(autouse=True)
def _hostile_parent_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # The parent process may itself run inside Claude Code or hold API keys.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fixture-never-forward")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "fixture-token-never-forward")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://fixture.invalid")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fixture-oauth-never-forward")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-fixture")


def test_argv_is_tool_free_isolated_schema_bound_and_never_bare(tmp_path: Path) -> None:
    executable = _install_fake(tmp_path, [_success({"value": "ok"})])
    provider = _provider(executable, effort="medium")

    result = provider.generate(
        subject_id="window_1",
        payload={"transcript": "UNTRUSTED-TRANSCRIPT-MARKER"},
        response_model=Answer,
    )

    assert result.output == Answer(value="ok")
    (call,) = _calls(executable)
    argv = call["argv"]
    assert "--bare" not in argv
    assert argv[0] == "--print"
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    assert argv[argv.index("--effort") + 1] == "medium"
    assert "--no-session-persistence" in argv
    assert "--tools=" in argv
    disallowed = argv[argv.index("--disallowed-tools") + 1].split(",")
    assert {"Bash", "Read", "Edit", "Write", "WebFetch", "WebSearch"} <= set(disallowed)
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    assert "--disable-slash-commands" in argv
    assert "--strict-mcp-config" in argv
    assert json.loads(argv[argv.index("--mcp-config") + 1]) == {"mcpServers": {}}
    assert "--setting-sources=" in argv
    assert "--safe-mode" in argv
    assert argv[argv.index("--system-prompt") + 1] == CLAUDE_SYSTEM_PROMPT
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["value"]
    # The LiveClip prompt and untrusted payload travel on stdin only.
    assert not any("UNTRUSTED-TRANSCRIPT-MARKER" in value for value in argv)
    assert "UNTRUSTED-TRANSCRIPT-MARKER" in call["stdin"]
    assert call["stdin"].startswith(provider._prompts.instructions)
    # A fresh empty working directory: no project files or CLAUDE.md to discover.
    assert call["cwd_entries"] == []
    assert Path(call["cwd"]).resolve() != Path.cwd().resolve()


def test_child_environment_is_allowlisted_and_never_carries_api_keys(tmp_path: Path) -> None:
    executable = _install_fake(tmp_path, [_success({"value": "ok"})])
    _provider(executable).generate(subject_id="s", payload={}, response_model=Answer)

    (call,) = _calls(executable)
    env = call["env"]
    assert not [key for key in env if key.upper().startswith(("ANTHROPIC_", "CLAUDE"))]
    assert "OPENAI_API_KEY" not in env
    assert "sk-ant-fixture-never-forward" not in json.dumps(call)
    allowed = {
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TMPDIR",
        "USER",
    }
    # macOS may add its own CoreFoundation locale hint to any child process.
    assert set(env) - {"__CF_USER_TEXT_ENCODING"} <= allowed


def test_environment_helper_drops_keys_even_with_lowercase_or_lookalike_names() -> None:
    source = {
        "HOME": "/home/fixture",
        "PATH": "/usr/bin",
        "ANTHROPIC_API_KEY": "secret",
        "anthropic_api_key": "secret",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDECODE": "1",
        "SSL_CERT_FILE": "/etc/ssl/cert.pem",
        "HTTPS_PROXY": "https://user:pass@proxy.invalid",
    }

    assert claude_cli_environment(source) == {
        "HOME": "/home/fixture",
        "PATH": "/usr/bin",
        "SSL_CERT_FILE": "/etc/ssl/cert.pem",
    }


@pytest.mark.parametrize(
    "version",
    ["2.1.308 (Claude Code)\n", "2.1.306 (Claude Code)\n", "2.1.307\n", "2.1.307 (Claude Code)\r"],
)
def test_unreviewed_or_malformed_version_is_refused_before_inference(
    tmp_path: Path, version: str
) -> None:
    executable = _install_fake(tmp_path, [_success({"value": "ok"})], version=version)

    with pytest.raises(ProviderConfigurationError) as error:
        _provider(executable)

    assert _calls(executable) == []
    if version.startswith(("2.1.308 (", "2.1.306 (")):
        assert SUPPORTED_CLAUDE_CLI_VERSION in str(error.value)
        assert "has not been reviewed" in str(error.value)


def test_structured_output_field_is_parsed_and_usage_is_recorded_without_session(
    tmp_path: Path,
) -> None:
    executable = _install_fake(
        tmp_path, [_success({"value": "from-structured"}, result_text='{"value":"other"}')]
    )
    provider = _provider(executable)

    result = provider.generate(subject_id="s", payload={}, response_model=Answer)

    assert result.output.value == "from-structured"
    (record,) = result.call_records
    assert record.provider == "claude_cli"
    assert record.model == "claude-opus-5-5"
    assert record.response_model == "claude-opus-5-5"
    assert record.status == ProviderCallStatus.SUCCEEDED
    assert record.request_count == 1 and record.retry_count == 0
    assert record.request_id is None
    assert record.usage_json == {
        "input_tokens": 1000,
        "uncached_input_tokens": 10,
        "cache_creation_input_tokens": 900,
        "cache_read_input_tokens": 90,
        "output_tokens": 40,
        "thinking_tokens": 5,
        "duration_api_ms": 1200,
        "num_turns": 2,
    }
    serialized = record.model_dump_json()
    assert "00000000-0000-4000-8000-000000000000" not in serialized
    assert "fixture-person" not in serialized


def test_schema_invalid_output_gets_exactly_one_repair(tmp_path: Path) -> None:
    executable = _install_fake(tmp_path, [_success({"value": 7}), _success({"value": "fixed"})])
    sleeps: list[float] = []

    result = _provider(executable, sleeps=sleeps).generate(
        subject_id="s", payload={}, response_model=Answer
    )

    assert result.repaired is True
    assert result.output.value == "fixed"
    first, second = result.call_records
    assert first.status == ProviderCallStatus.INVALID
    assert first.failure_code == "STRUCTURED_OUTPUT_INVALID"
    assert second.status == ProviderCallStatus.SUCCEEDED
    assert [record.operation.rsplit(".", 1)[-1] for record in result.call_records] == [
        "initial",
        "repair",
    ]
    calls = _calls(executable)
    assert len(calls) == 2
    assert (
        load_dual_profile_prompt("discovery", ClipProfile.SHORT_HIGHLIGHT).repair
        in (calls[1]["stdin"])
    )
    assert sleeps == []


def test_schema_failures_are_never_treated_as_rate_limits(tmp_path: Path) -> None:
    executable = _install_fake(tmp_path, [_success({"value": 7})])
    sleeps: list[float] = []

    with pytest.raises(StructuredProviderError) as error:
        _provider(executable, sleeps=sleeps).generate(
            subject_id="s", payload={}, response_model=Answer
        )

    assert error.value.code == "STRUCTURED_OUTPUT_INVALID"
    assert str(error.value) == "structured model output could not be validated"
    assert sleeps == []
    assert len(_calls(executable)) == 2


def test_missing_structured_output_is_a_repairable_schema_failure(tmp_path: Path) -> None:
    executable = _install_fake(tmp_path, [_success(None), _success({"value": "fixed"})])

    result = _provider(executable).generate(subject_id="s", payload={}, response_model=Answer)

    assert result.repaired is True
    assert result.call_records[0].failure_code == "STRUCTURED_OUTPUT_INVALID"


def test_rate_limit_then_success_backs_off_with_jitter_and_counts_retries(
    tmp_path: Path,
) -> None:
    executable = _install_fake(
        tmp_path,
        [
            _api_error(429, "API Error: 429 rate_limit_error"),
            _api_error(529, "API Error: 529 Overloaded"),
            _success({"value": "ok"}),
        ],
    )
    sleeps: list[float] = []

    result = _provider(executable, sleeps=sleeps).generate(
        subject_id="s", payload={}, response_model=Answer
    )

    assert result.output.value == "ok"
    # Equal jitter at 0.5: half of each 2 s / 4 s ceiling plus half of the rest.
    assert sleeps == [1.5, 3.0]
    (record,) = result.call_records
    assert record.status == ProviderCallStatus.SUCCEEDED
    assert record.request_count == 3
    assert record.retry_count == 2
    assert len(_calls(executable)) == 3


def test_rate_limit_exhaustion_names_the_real_cause(tmp_path: Path) -> None:
    executable = _install_fake(tmp_path, [_api_error(429, "API Error: 429 Too Many Requests")])
    sleeps: list[float] = []
    policy = ClaudeCliRetryPolicy(
        max_attempts=3, base_delay_seconds=1.0, max_delay_seconds=2.0, total_wait_seconds=60.0
    )

    with pytest.raises(StructuredProviderError) as error:
        _provider(executable, policy=policy, sleeps=sleeps).generate(
            subject_id="s", payload={}, response_model=Answer
        )

    assert error.value.code == "CLAUDE_CLI_RATE_LIMITED"
    assert str(error.value) == "Claude CLI rate limited (429) after 3 attempts"
    assert "could not be validated" not in str(error.value)
    (record,) = error.value.call_records
    assert record.status == ProviderCallStatus.FAILED
    assert record.request_count == 3 and record.retry_count == 2
    assert sleeps == [0.75, 1.5]
    # A rate limit never consumes the schema repair.
    assert len(_calls(executable)) == 3


def test_total_wait_cap_stops_retrying_before_the_attempt_limit(tmp_path: Path) -> None:
    executable = _install_fake(tmp_path, [_api_error(529, "Overloaded")])
    sleeps: list[float] = []
    policy = ClaudeCliRetryPolicy(
        max_attempts=6, base_delay_seconds=4.0, max_delay_seconds=60.0, total_wait_seconds=10.0
    )

    with pytest.raises(StructuredProviderError) as error:
        _provider(executable, policy=policy, sleeps=sleeps).generate(
            subject_id="s", payload={}, response_model=Answer
        )

    assert sleeps == [3.0, 6.0]
    assert str(error.value) == "Claude CLI API overloaded (529) after 3 attempts"


def test_subscription_usage_limit_is_not_retried(tmp_path: Path) -> None:
    executable = _install_fake(
        tmp_path, [_api_error(429, "Claude AI usage limit reached|1760000000")]
    )
    sleeps: list[float] = []

    with pytest.raises(StructuredProviderError) as error:
        _provider(executable, sleeps=sleeps).generate(
            subject_id="s", payload={}, response_model=Answer
        )

    assert error.value.code == "CLAUDE_CLI_USAGE_LIMIT_REACHED"
    assert "usage limit reached" in str(error.value)
    assert sleeps == []
    assert len(_calls(executable)) == 1


def test_tool_activity_in_the_result_fails_closed(tmp_path: Path) -> None:
    response = _success({"value": "ok"})
    response["stdout"]["permission_denials"] = [{"tool_name": "Bash"}]
    executable = _install_fake(tmp_path, [response])

    with pytest.raises(StructuredProviderError) as error:
        _provider(executable).generate(subject_id="s", payload={}, response_model=Answer)

    assert error.value.code == "STRUCTURED_TOOL_EVENT"


def test_an_answer_from_another_model_is_rejected(tmp_path: Path) -> None:
    response = _success({"value": "ok"})
    response["stdout"]["modelUsage"] = {"claude-haiku-9": {}}
    executable = _install_fake(tmp_path, [response])

    with pytest.raises(StructuredProviderError) as error:
        _provider(executable).generate(subject_id="s", payload={}, response_model=Answer)

    assert error.value.code == "CLAUDE_CLI_MODEL_MISMATCH"


@pytest.mark.parametrize(
    ("status", "text", "code"),
    [
        (429, "API Error: 429", "CLAUDE_CLI_RATE_LIMITED"),
        (None, "Request rejected: rate limit reached", "CLAUDE_CLI_RATE_LIMITED"),
        (529, "", "CLAUDE_CLI_OVERLOADED"),
        (None, '{"type":"overloaded_error"}', "CLAUDE_CLI_OVERLOADED"),
        (503, "", "CLAUDE_CLI_SERVICE_UNAVAILABLE"),
        (None, "API Error: Connection error.", "CLAUDE_CLI_CONNECTION_FAILED"),
        (429, "You've hit your limit · resets 5pm", "CLAUDE_CLI_USAGE_LIMIT_REACHED"),
        (None, "Not logged in · Please run /login", "CLAUDE_CLI_AUTH_FAILED"),
        (404, "There's an issue with the selected model", "CLAUDE_CLI_MODEL_UNAVAILABLE"),
        (None, "Prompt is too long", "CLAUDE_CLI_CONTEXT_WINDOW_EXCEEDED"),
        (None, "something else", "CLAUDE_CLI_REQUEST_FAILED"),
    ],
)
def test_failure_classification(status: int | None, text: str, code: str) -> None:
    assert classify_claude_cli_failure(status, text) == code


def test_contract_identity_pins_version_argv_template_and_differs_from_codex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = _install_fake(tmp_path, [])

    contract = claude_cli_contract_version(str(executable))

    assert contract.startswith(f"claude-cli-editorial-v1.{SUPPORTED_CLAUDE_CLI_VERSION}.")
    assert not contract.startswith(codex_module.CODEX_LLM_CONTRACT_PREFIX)
    monkeypatch.setattr(claude_module, "CLAUDE_SYSTEM_PROMPT", "A different system prompt.")
    assert claude_cli_contract_version(str(executable)) != contract

    codex_contract = f"{codex_module.CODEX_LLM_CONTRACT_PREFIX}.0.154.0.{'a' * 64}"
    keys = {
        semantic_cache_key(
            source_hash="f" * 64,
            profile=ClipProfile.SHORT_HIGHLIGHT,
            window_start=0,
            window_end=1,
            prompt_hash="e" * 64,
            model="same-model",
            model_settings={"reasoning_effort": "medium", "contract_version": value},
        )
        for value in (contract, codex_contract)
    }
    assert len(keys) == 2


def test_contract_drift_between_calls_is_refused(tmp_path: Path) -> None:
    executable = _install_fake(tmp_path, [_success({"value": "ok"})])
    provider = _provider(executable)
    executable.write_text(executable.read_text() + "\n# upgraded\n", encoding="utf-8")

    with pytest.raises(ProviderConfigurationError):
        provider.generate(subject_id="s", payload={}, response_model=Answer)
    assert _calls(executable) == []


@pytest.mark.parametrize(
    "auth",
    [
        {"loggedIn": True, "authMethod": "apiKey", "apiProvider": "firstParty"},
        {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "bedrock"},
        {"loggedIn": False},
    ],
)
def test_readiness_refuses_anything_but_a_subscription_login(
    tmp_path: Path, auth: dict[str, object]
) -> None:
    executable = _install_fake(tmp_path, [], auth=auth)

    with pytest.raises(ProviderConfigurationError):
        assert_claude_cli_ready(str(executable))


def test_settings_select_the_claude_cli_with_stage_efforts(tmp_path: Path) -> None:
    executable = _install_fake(tmp_path, [])
    settings = Settings(
        ai_provider="openrouter-codex",
        structured_provider="claude-cli",
        claude_executable=str(executable),
    )
    prompt = load_dual_profile_prompt("discovery", ClipProfile.MINI_LESSON)

    factory = configured_structured_editorial_provider_factory(settings)
    discovery = factory(prompt, "medium")
    review = factory(prompt, "high")

    assert isinstance(discovery, ClaudeCliStructuredLLMProvider)
    assert discovery.provider_name == "claude_cli"
    assert discovery.model_name == "claude-opus-5-5"
    assert discovery.reasoning_effort == "medium"
    assert getattr(review, "reasoning_effort", None) == "high"
    assert discovery.contract_version == review.contract_version
    assert discovery.retry_policy == ClaudeCliRetryPolicy()
    assert _calls(executable) == []


def test_auto_selection_keeps_codex_for_codex_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    contract = f"{codex_module.CODEX_LLM_CONTRACT_PREFIX}.0.154.0.{'a' * 64}"
    monkeypatch.setattr(codex_module, "resolve_codex_executable", lambda _value: "/codex")
    monkeypatch.setattr(codex_module, "codex_cli_contract_version", lambda _value: contract)
    monkeypatch.setattr(
        "liveclip.services.structured_editorial_provider.codex_cli_contract_version",
        lambda _value: contract,
    )
    monkeypatch.setattr(
        "liveclip.services.structured_editorial_provider.assert_claude_cli_ready",
        lambda _value: pytest.fail("Claude must not be probed when not selected"),
    )
    factory = configured_structured_editorial_provider_factory(
        Settings(ai_provider="openrouter-codex")
    )

    provider = factory(load_dual_profile_prompt("discovery", ClipProfile.MINI_LESSON), "medium")

    assert isinstance(provider, structured_module.CodexStructuredLLMProvider)
    assert provider.provider_name == "codex_cli"


def test_settings_validate_structured_provider_and_claude_defaults() -> None:
    settings = Settings()
    assert settings.structured_provider == "auto"
    assert settings.claude_executable == "claude"
    assert settings.claude_model == "claude-opus-5-5"
    assert Settings(structured_provider=" Claude-CLI ").structured_provider == "claude-cli"
    with pytest.raises(ValueError):
        Settings(structured_provider="claude")
    with pytest.raises(ValueError):
        Settings(claude_model="opus; rm -rf /")
    with pytest.raises(ValueError):
        Settings(claude_retry_base_seconds=90, claude_retry_max_seconds=30)


def test_doctor_reports_only_login_booleans_and_method_type(tmp_path: Path) -> None:
    executable = _install_fake(tmp_path, [])
    settings = Settings(structured_provider="claude-cli", claude_executable=str(executable))

    check = doctor_module._claude_cli_check(settings)

    assert check.name == "claude_cli"
    assert check.status == "pass"
    assert check.details["logged_in"] is True
    assert check.details["auth_method"] == "claude.ai"
    assert check.details["subscription"] is True
    assert check.details["reviewed_version"] == SUPPORTED_CLAUDE_CLI_VERSION
    assert str(check.details["contract"]).startswith("claude-cli-editorial-v1.")
    serialized = json.dumps(check.as_dict())
    assert "fixture-person" not in serialized
    assert "Fixture Org" not in serialized


def test_doctor_fails_for_api_key_login_and_skips_when_not_selected(tmp_path: Path) -> None:
    executable = _install_fake(
        tmp_path, [], auth={"loggedIn": True, "authMethod": "apiKey", "apiProvider": "firstParty"}
    )

    selected = doctor_module._claude_cli_check(
        Settings(structured_provider="claude-cli", claude_executable=str(executable))
    )
    unselected = doctor_module._claude_cli_check(Settings(structured_provider="auto"))

    assert selected.status == "fail"
    assert selected.details["subscription"] is False
    assert unselected.status == "pass"
    assert unselected.details == {"selected": False}


def test_doctor_reports_unreviewed_versions_as_failures(tmp_path: Path) -> None:
    executable = _install_fake(tmp_path, [], version="9.9.9 (Claude Code)\n")

    check = doctor_module._claude_cli_check(
        Settings(structured_provider="claude-cli", claude_executable=str(executable))
    )

    assert check.status == "fail"
    assert check.details["error"] == "ProviderConfigurationError"


def test_smoke_makes_one_real_shaped_call_and_reports_safe_evidence(tmp_path: Path) -> None:
    suggestion = {
        "source_start_ms": 12_000,
        "source_end_ms": 52_000,
        "score": 88,
        "title": "开头三秒",
        "hook": "先说为什么值得看",
    }
    executable = _install_fake(tmp_path, [_success(suggestion)])

    result = run_claude_smoke(
        Settings(structured_provider="claude-cli", claude_executable=str(executable))
    )

    assert result.provider == "claude_cli"
    assert result.model == result.response_model == "claude-opus-5-5"
    assert result.auth_method == "claude.ai"
    assert result.request_count == 1
    assert (result.input_tokens, result.output_tokens) == (1000, 40)
    assert (result.source_start_ms, result.source_end_ms) == (12_000, 52_000)
    (call,) = _calls(executable)
    assert call["argv"][call["argv"].index("--effort") + 1] == "medium"


def test_smoke_fails_without_mock_fallback_on_out_of_range_boundaries(tmp_path: Path) -> None:
    suggestion = {
        "source_start_ms": 0,
        "source_end_ms": 90_000,
        "score": 88,
        "title": "越界",
        "hook": "越界",
    }
    executable = _install_fake(tmp_path, [_success(suggestion)])

    with pytest.raises(ClaudeSmokeError):
        run_claude_smoke(Settings(claude_executable=str(executable)))
