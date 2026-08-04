from __future__ import annotations

from pathlib import Path

import pytest

from liveclip.config.settings import Settings
from liveclip.services import cloud_smoke
from liveclip.services.cloud_smoke import (
    CloudPlanEvidence,
    CloudSmokeError,
    CloudUsageEvidence,
    cloud_smoke_preflight,
    run_cloud_smoke,
    validate_cloud_smoke_evidence,
)


def test_cloud_smoke_preflight_reports_all_missing_configuration(tmp_path: Path) -> None:
    settings = Settings(
        ai_provider="mock",
        allowed_media_roots_raw="",
        openai_api_key=None,
        transcription_model="gpt-4o-transcribe",
        llm_model="bad model name",
        _env_file=None,
    )

    issues = cloud_smoke_preflight(settings, tmp_path / "missing.mp4")

    assert "LIVECLIP_AI_PROVIDER=openai" in issues
    assert "OPENAI_API_KEY" in issues
    assert "OPENAI_TRANSCRIPTION_MODEL=whisper-1 (timestamp contract)" in issues
    assert "OPENAI_LLM_MODEL" in issues
    assert "LIVECLIP_ALLOWED_MEDIA_ROOTS" in issues
    assert "INPUT must be an existing regular file" in issues


def test_cloud_smoke_preflight_never_opens_database_or_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = False

    def fail_if_opened(*_args: object, **_kwargs: object) -> object:
        nonlocal opened
        opened = True
        raise AssertionError("runtime must not open after failed preflight")

    monkeypatch.setattr(cloud_smoke.LiveClipRuntime, "open", fail_if_opened)
    settings = Settings(ai_provider="mock", _env_file=None)

    with pytest.raises(CloudSmokeError, match="not_run"):
        run_cloud_smoke(settings=settings, input_path=tmp_path / "missing.mp4")

    assert opened is False


def _usage(**changes: object) -> CloudUsageEvidence:
    payload: dict[str, object] = {
        "provider": "openai",
        "operation": "audio.transcriptions",
        "model": "whisper-1",
        "request_id": "req_asr",
        "status": "succeeded",
    }
    payload.update(changes)
    return CloudUsageEvidence(**payload)  # type: ignore[arg-type]


def _valid_evidence() -> tuple[CloudUsageEvidence, ...]:
    return (
        _usage(),
        _usage(
            operation="responses.edit.initial",
            model="gpt-5.6-terra",
            request_id="req_llm",
        ),
    )


def test_cloud_evidence_accepts_only_traceable_real_success() -> None:
    result = validate_cloud_smoke_evidence(
        transcript_provider="openai",
        usage=_valid_evidence(),
        selected_plans=(CloudPlanEvidence(degraded=False, model="gpt-5.6-terra"),),
        expected_asr_model="whisper-1",
        expected_llm_model="gpt-5.6-terra",
    )

    assert result == (("req_asr",), ("req_llm",))


@pytest.mark.parametrize(
    ("usage", "plans", "message"),
    [
        (
            (_usage(request_id=None), _valid_evidence()[1]),
            (CloudPlanEvidence(degraded=False, model="gpt-5.6-terra"),),
            "ASR evidence",
        ),
        (
            _valid_evidence(),
            (CloudPlanEvidence(degraded=True, model="gpt-5.6-terra"),),
            "degraded",
        ),
        (
            (_usage(provider="mock"), _valid_evidence()[1]),
            (CloudPlanEvidence(degraded=False, model="gpt-5.6-terra"),),
            "non-OpenAI",
        ),
        (
            (_usage(status="failed"), _valid_evidence()[1]),
            (CloudPlanEvidence(degraded=False, model="gpt-5.6-terra"),),
            "failed provider",
        ),
    ],
    ids=["missing-request-id", "degraded-plan", "mock-evidence", "failed-evidence"],
)
def test_cloud_evidence_refuses_false_success(
    usage: tuple[CloudUsageEvidence, ...],
    plans: tuple[CloudPlanEvidence, ...],
    message: str,
) -> None:
    with pytest.raises(CloudSmokeError, match=message):
        validate_cloud_smoke_evidence(
            transcript_provider="openai",
            usage=usage,
            selected_plans=plans,
            expected_asr_model="whisper-1",
            expected_llm_model="gpt-5.6-terra",
        )
