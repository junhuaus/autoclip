"""Stage 12/12b: the dual-profile flag contract in prompts matches the code; the
stale-cache refresh is an explicit opt-in."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import liveclip.cli.app as cli_module
from liveclip.clipping_skills.dual_profile_v1 import load_dual_profile_prompt
from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.dual_profile import (
    AUTO_BLOCKING_QUALITY_FLAGS,
    MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS,
    PADDING_GATED_FLAGS,
    PERSISTED_STRUCTURAL_GATED_FLAGS,
    DualQualityFlag,
)
from liveclip.services.dual_profile_evaluation import (
    DualProfileValidationAttempt,
    DualProfileValidationExhaustedError,
)

GATED_LABEL = "Gated flags (Python forces `blocked`):"
ADVISORY_LABEL = "Advisory flags (Python only forbids `selected`):"


def _text(stage: str, profile: ClipProfile) -> str:
    return " ".join(load_dual_profile_prompt(stage, profile).instructions.split())


def _listed(text: str, label: str) -> set[str]:
    assert text.count(label) == 1, label
    sentence = text.split(label, 1)[1].split(".", 1)[0]
    return set(re.findall(r"`([a-z_]+)`", sentence))


@pytest.mark.parametrize("stage", ["global_review", "global_audit"])
@pytest.mark.parametrize("profile", list(ClipProfile))
def test_review_prompts_list_exactly_the_gated_and_advisory_flags(
    stage: str, profile: ClipProfile
) -> None:
    text = _text(stage, profile)
    gated = {flag.value for flag in MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS}
    advisory = {
        flag.value for flag in AUTO_BLOCKING_QUALITY_FLAGS - MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS
    }
    assert _listed(text, GATED_LABEL) == gated
    assert _listed(text, ADVISORY_LABEL) == advisory
    assert gated | advisory == {flag.value for flag in DualQualityFlag}
    assert not gated & advisory
    # The old over-claim drove coherent advisory-only candidates to `blocked`.
    assert "enforces every unresolved flag" not in text
    assert "Boundary Review quality flags are cumulative" in text
    assert "state the disagreement in `review_reason`" in text


# Stage 14: every Discovery pass and Boundary Review load the shared main.md,
# which carries the microphone/demonstration rule and the padding-is-edge rule.
DISCOVERY_AND_BOUNDARY_STAGES = (
    "discovery",
    "coverage_audit",
    "precision_audit",
    "precision_confirmation",
    "risk_discovery",
    "boundary_review",
)
PADDING_EDGE_LABEL = "Padding flags ("
MIC_DEMO_RULE = (
    "Brief microphone, distance, placement or equipment words that directly enable an immediate "
    "live vocal demonstration, including why moving closer helps listeners hear, are part of that "
    "demonstration: they are neither padding nor an interruption."
)


@pytest.mark.parametrize("stage", DISCOVERY_AND_BOUNDARY_STAGES)
@pytest.mark.parametrize("profile", list(ClipProfile))
def test_every_discovery_pass_and_boundary_review_share_the_padding_and_demo_rules(
    stage: str, profile: ClipProfile
) -> None:
    prompt = load_dual_profile_prompt(stage, profile)
    assert "dual_profile_v1/main.md" in prompt.loaded_files
    text = _text(stage, profile)
    assert MIC_DEMO_RULE in text
    assert text.count(PADDING_EDGE_LABEL) == 1
    rule = text.split(PADDING_EDGE_LABEL, 1)[1]
    listed = set(re.findall(r"`([a-z_]+)`", rule.split(")", 1)[0]))
    assert listed == {flag.value for flag in PADDING_GATED_FLAGS}
    assert "describe EDGE material only" in rule
    assert (
        "Unrelated content inside the interval, between on-topic cues, is `material_interruption`, "
        "or `topic_switch_inside` when another topic starts inside the interval" in rule
    )


INTERIOR_PADDING_RULE = {
    "boundary_review": (
        "are `device_or_waiting_padding` at an edge of the interval. Inside the interval, between "
        "on-topic cues, the same content is `material_interruption`; `device_or_waiting_padding` "
        "may be added alongside that interior flag, never used instead of it."
    ),
    "global_review": (
        "are padding at an edge of the interval. Inside the interval, between on-topic cues, they "
        "are `material_interruption`; a padding flag may be added alongside that interior flag, "
        "never used instead of it."
    ),
    "global_audit": (
        "at an edge they are padding; inside the interval, between on-topic cues, they are "
        "`material_interruption`, and a padding flag may be added alongside that interior flag, "
        "never used instead of it;"
    ),
    "risk_discovery": (
        "flag each interior interruption as `material_interruption` (or `topic_switch_inside` "
        "when another topic starts inside the chain)"
    ),
    "coverage_audit": (
        "Flag each interior interruption as `material_interruption` (or `topic_switch_inside` "
        "when another topic starts inside the chain)"
    ),
}


@pytest.mark.parametrize("stage", sorted(INTERIOR_PADDING_RULE))
@pytest.mark.parametrize("profile", list(ClipProfile))
def test_prompts_name_interior_interruptions_and_keep_padding_flags_at_the_edges(
    stage: str, profile: ClipProfile
) -> None:
    """Stage 14b: aligned with main.md, interior audibility/device trouble and
    interior sales/device interruptions are `material_interruption`; padding
    flags describe edge material only and may accompany, never replace it."""

    text = _text(stage, profile)
    assert INTERIOR_PADDING_RULE[stage] in text
    # The superseded wording made interior trouble padding first.
    assert "are padding (and an interruption when they split" not in text
    assert "`material_interruption` when they split a demonstration" not in text
    assert "attach the corresponding quality flags" not in text.lower()
    if stage in {"risk_discovery", "coverage_audit"}:
        assert "padding flags describe edge material only" in text.lower()
        assert "never replace" in text


@pytest.mark.parametrize("stage", ["global_review", "global_audit"])
@pytest.mark.parametrize("profile", list(ClipProfile))
def test_review_prompts_state_that_only_structural_discovery_flags_persist(
    stage: str, profile: ClipProfile
) -> None:
    text = _text(stage, profile)
    marker = (
        "but only a structural one ("
        if stage == "global_review"
        else "lists the structural Discovery gated flags ("
    )
    assert text.count(marker) == 1
    structural = set(re.findall(r"`([a-z_]+)`", text.split(marker, 1)[1].split(")", 1)[0]))
    assert structural == {flag.value for flag in PERSISTED_STRUCTURAL_GATED_FLAGS}
    padding_marker = "Discovery padding flags ("
    assert text.count(padding_marker) == 1
    padding = set(re.findall(r"`([a-z_]+)`", text.split(padding_marker, 1)[1].split(")", 1)[0]))
    assert padding == {flag.value for flag in PADDING_GATED_FLAGS}
    assert "they follow Boundary Review, the edge authority" in text
    if stage == "global_audit":
        assert (
            'Do not block a candidate, or change its status "to match routing", because '
            "Discovery raised a padding flag that Boundary Review cleared" in text
        )
    else:
        assert "do not block it merely because Discovery raised that padding flag" in text


def test_advisory_set_is_the_documented_context_and_title_flags() -> None:
    assert {
        DualQualityFlag.CONTEXT_DEPENDENT_OPENING,
        DualQualityFlag.MISSING_REQUIRED_PRIOR_STEPS,
        DualQualityFlag.SOURCE_TITLE_MISMATCH,
    } == AUTO_BLOCKING_QUALITY_FLAGS - MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS


@pytest.mark.parametrize("profile", list(ClipProfile))
def test_boundary_prompt_states_the_opening_flag_invariant(profile: ClipProfile) -> None:
    text = _text("boundary_review", profile)
    assert (
        "A review item that keeps `context_dependent_opening` must set `opening_complete` to false"
        in text
    )


@pytest.mark.parametrize("profile", list(ClipProfile))
def test_audit_prompt_allows_duplicate_pairs_through_a_shared_representative(
    profile: ClipProfile,
) -> None:
    text = _text("global_audit", profile)
    assert "duplicates of the same third representative" in text


@pytest.mark.parametrize(
    ("arguments", "expected"), [((), False), (("--refresh-stale-cache",), True)]
)
def test_dual_profile_eval_cli_stale_cache_refresh_is_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: tuple[str, ...], expected: bool
) -> None:
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(cli_module, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(
        cli_module, "configured_dual_profile_provider_factory", lambda _settings: None
    )
    monkeypatch.setattr(cli_module, "run_dual_profile_evaluation", fake_run)
    result = CliRunner().invoke(
        cli_module.app,
        [
            "dual-profile-eval",
            "--transcript",
            str(tmp_path / "transcript.srt"),
            "--output",
            str(tmp_path / "output"),
            *arguments,
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["refresh_stale_cache"] is expected


def test_dual_profile_eval_cli_exits_nonzero_with_a_bounded_failure_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage 13d: an exhausted validation names its unit and evidence file."""

    long_error = "; ".join(f"duplicate cand_{index} (status blocked)" for index in range(40))
    error = DualProfileValidationExhaustedError(
        stage="global_audit",
        profile="short_highlight",
        subject_id="short_highlight.global_audit",
        cache_key="a" * 64,
        attempts=(DualProfileValidationAttempt(phase="initial", output={}, error=long_error),),
        records=(),
        final_error=ValueError(long_error),
    )
    error.evidence_file = str(tmp_path / "output" / error.failure_file_name)

    def fake_run(**_kwargs: object) -> dict[str, object]:
        raise error

    monkeypatch.setattr(cli_module, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(
        cli_module, "configured_dual_profile_provider_factory", lambda _settings: None
    )
    monkeypatch.setattr(cli_module, "run_dual_profile_evaluation", fake_run)
    result = CliRunner().invoke(
        cli_module.app,
        [
            "dual-profile-eval",
            "--transcript",
            str(tmp_path / "transcript.srt"),
            "--output",
            str(tmp_path / "output"),
        ],
    )
    assert result.exit_code == 1
    assert len(str(error)) > 500
    assert (
        "dual Profile validation exhausted after one repair and one regeneration in "
        "short_highlight global_audit (short_highlight.global_audit); evidence: "
    ) in result.output
    assert "failed-short_highlight-global_audit.json; last error: duplicate cand_0" in (
        result.output
    )


def test_dual_profile_eval_cli_summary_keeps_the_evidence_writer_failure_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage 14 P3: when the evidence writer itself failed, the CLI says so."""

    long_error = "; ".join(f"duplicate cand_{index} (status blocked)" for index in range(40))
    error = DualProfileValidationExhaustedError(
        stage="global_audit",
        profile="mini_lesson",
        subject_id="mini_lesson.global_audit",
        cache_key="b" * 64,
        attempts=(DualProfileValidationAttempt(phase="initial", output={}, error=long_error),),
        records=(),
        final_error=ValueError(long_error),
    )
    # The service adds this note (and leaves evidence_file unset) when
    # _write_validation_failure raises.
    error.add_note("failure evidence could not be written: OSError: disk full")

    def fake_run(**_kwargs: object) -> dict[str, object]:
        raise error

    monkeypatch.setattr(cli_module, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(
        cli_module, "configured_dual_profile_provider_factory", lambda _settings: None
    )
    monkeypatch.setattr(cli_module, "run_dual_profile_evaluation", fake_run)
    result = CliRunner().invoke(
        cli_module.app,
        [
            "dual-profile-eval",
            "--transcript",
            str(tmp_path / "transcript.srt"),
            "--output",
            str(tmp_path / "output"),
        ],
    )
    assert result.exit_code == 1
    assert "evidence: " not in result.output
    assert (
        "(mini_lesson.global_audit); failure evidence could not be written: OSError: disk full; "
        "last error: duplicate cand_0"
    ) in result.output
    # A very long note is truncated so the summary stays bounded.
    error.add_note("x" * 1_000)
    summary = error.summary()
    assert len(summary) <= 500
    assert "failure evidence could not be written: OSError: disk full" in summary
