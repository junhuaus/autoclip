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
        "flag each interior interruption that breaks the claim logic as `material_interruption` "
        "(or `topic_switch_inside` when another topic starts inside the chain)"
    ),
    "coverage_audit": (
        "Flag each interior interruption that breaks the claim logic as `material_interruption` "
        "(or `topic_switch_inside` when another topic starts inside the chain)"
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


# Stage 15: the `material_interruption` threshold (fix of a Stage 14/14b
# over-broadening).  main.md is shared by every stage; the two risk-chain
# Discovery passes mirror it in their own stage text.
ALL_STAGES = (*DISCOVERY_AND_BOUNDARY_STAGES, "global_review", "global_audit")
MI_THRESHOLD = (
    "Interior content counts as `material_interruption` only when it actually breaks the "
    "teaching or claim logic; a brief audience thanks, greeting, name call-out or "
    "acknowledgement that the speaker passes over without leaving the topic is neither an "
    "interruption nor padding."
)


def _stage_text(stage: str, profile: ClipProfile) -> str:
    """Only the stage file's own text (after main.md and the Profile file)."""

    text = load_dual_profile_prompt(stage, profile).instructions
    return " ".join(text[text.index("# Stage:") :].split())


@pytest.mark.parametrize("stage", ALL_STAGES)
@pytest.mark.parametrize("profile", list(ClipProfile))
def test_every_stage_carries_the_material_interruption_threshold(
    stage: str, profile: ClipProfile
) -> None:
    text = _text(stage, profile)
    assert MI_THRESHOLD in text
    # The Stage 14 rules stay: padding is edge-only, interior unrelated content is
    # the interior flag, and the live-demo equipment remark is part of the demo.
    assert "describe EDGE material only" in text
    assert MIC_DEMO_RULE in text
    assert re.search(r"\d", MI_THRESHOLD) is None
    if stage in {"risk_discovery", "coverage_audit"}:
        own = _stage_text(stage, profile)
        assert MI_THRESHOLD in own
        assert "interior interruption that breaks the claim logic as `material_interruption`" in (
            own
        )
    if stage == "risk_discovery":
        own = _stage_text(stage, profile)
        assert "Mark the interruption, but keep" not in own
        assert "Mark an interruption only when it breaks the claim logic" in own
    if stage == "precision_audit":
        own = _stage_text(stage, profile)
        assert "Greetings inside that chain are quality evidence" not in own
        assert "flag it only under the main contract's `material_interruption` threshold" in own


@pytest.mark.parametrize("profile", list(ClipProfile))
def test_boundary_review_threshold_matches_the_shared_definition(profile: ClipProfile) -> None:
    text = _stage_text("boundary_review", profile)
    assert (
        "`material_interruption` requires unrelated semantic content that actually breaks the "
        "teaching or claim logic; silence, an ASR gap, a vocal demonstration, a self-correction, "
        "a brief audience thanks, greeting, name call-out or acknowledgement that the speaker "
        "passes over without leaving the topic, or the speaker's brief equipment or listening "
        "explanation attached to an immediate live example is not by itself an interruption."
    ) in text
    # Stage 14c cross-reference kept.
    assert (
        "Interior audibility checks, connection lag and playback trouble, as described below, are "
        "such unrelated content and count as `material_interruption`." in text
    )


@pytest.mark.parametrize("profile", list(ClipProfile))
def test_boundary_review_duration_test_obeys_the_interruption_threshold(
    profile: ClipProfile,
) -> None:
    """Stage 15b (reviewer P3-b): the on-topic duration test subtracts only interior
    material that meets the `material_interruption` threshold; a brief passed-over
    greeting or thanks is neither flag and is not removed."""

    text = _stage_text("boundary_review", profile)
    assert (
        "If removing interior material that meets the `material_interruption` threshold above "
        "(audience chat, comment reading, calls to action or device talk that breaks the "
        "teaching or claim logic), or edge setup kept only for duration, would leave a clip "
        "that no longer satisfies the Profile duration minimum, flag "
        "`padded_with_irrelevant_content`."
    ) in text
    assert (
        "flag `padded_with_irrelevant_content` alongside `material_interruption` (or "
        "`topic_switch_inside`), never instead of it."
    ) in text
    assert (
        "A brief audience thanks, greeting, name call-out or acknowledgement that the speaker "
        "passes over without leaving the topic is neither flag and is not removed in this test"
    ) in text
    # The superseded wording subtracted every greeting and then required both flags.
    assert "calls to action, greetings or device talk" not in text
    assert re.search(r"\d", text[text.index("The Profile minimum must be met") :][:900]) is None


SELF_PROMOTION_OBJECTIVE = (
    "whose central objective is the speaker's own credentials, qualifications, pricing, course "
    "sales or schedule"
)


@pytest.mark.parametrize("stage", ["boundary_review", "global_review", "global_audit"])
@pytest.mark.parametrize("profile", list(ClipProfile))
def test_review_prompts_reject_self_promotion_as_the_central_objective(
    stage: str, profile: ClipProfile
) -> None:
    text = _stage_text(stage, profile)
    assert text.count(SELF_PROMOTION_OBJECTIVE) == 1
    # The rule runs to its closing "... does not make that lesson self-promotion".
    rule = text.split(SELF_PROMOTION_OBJECTIVE, 1)[1].split("lesson self-promotion", 1)[0]
    assert "not a teaching or highlight unit" in rule
    assert "even when no explicit purchase prompt appears" in rule
    assert "a brief credential or course mention inside a real lesson does not make" in (
        rule.lower()
    )
    if stage == "boundary_review":
        assert "set `central_objective_complete` to false" in rule
        assert "so Global Review rejects it" in rule
        assert "do not treat clearing a padding flag as resolving it" in rule
    else:
        assert "`rejected`" in rule
        assert "not merely flagged" in rule
    assert re.search(r"\d", rule) is None


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
