from __future__ import annotations

import pytest

from liveclip.domain.edit_plan import CaptionCue
from liveclip.domain.releases import (
    PlatformPresetRegistry,
    ReleaseApprovalStatus,
    ReleaseCaptionMode,
    ReleaseChecklist,
    ReleaseDuplicateContentMatch,
    ReleaseEditorialFacts,
    ReleaseItemStatus,
    ReleaseMediaFacts,
    ReleasePackageStatus,
    ReleasePlatform,
    ReleaseTransitionError,
    evaluate_release_preflight,
    get_platform_preset,
    list_platform_presets,
    transition_release_approval,
    transition_release_item,
    transition_release_package,
)


def _checklist(**changes: bool) -> ReleaseChecklist:
    values = {name: True for name in ReleaseChecklist.model_fields}
    values.update(changes)
    return ReleaseChecklist.model_validate(values)


def _media(**changes: object) -> ReleaseMediaFacts:
    values: dict[str, object] = {
        "available": True,
        "trusted_render_contract": True,
        "container": "mp4",
        "video_codec": "h264",
        "audio_codec": "aac",
        "pixel_format": "yuv420p",
        "progressive": True,
        "fast_start": True,
        "full_decode": True,
        "width": 1080,
        "height": 1920,
        "duration_ms": 59_000,
        "size_bytes": 2_000_000,
        "separate_subtitle_available": True,
        "format_evidence": "actual_bytes",
    }
    values.update(changes)
    return ReleaseMediaFacts.model_validate(values)


def _editorial(**changes: object) -> ReleaseEditorialFacts:
    values: dict[str, object] = {
        "selected_revision": 2,
        "current_revision": 2,
        "clip_review_approved": True,
        "release_approval": ReleaseApprovalStatus.APPROVED,
        "title": "一个可发布的高光标题",
        "description": "可编辑发布说明",
        "hashtags": ("直播高光",),
        "cover_time_ms": 1_000,
        "caption_mode": ReleaseCaptionMode.CLEAN_SEPARATE,
        "captions": (CaptionCue(start_ms=0, end_ms=2_000, text="字幕可读"),),
        "risk_flags": (),
        "checklist": _checklist(),
        "current_project_run": True,
    }
    values.update(changes)
    return ReleaseEditorialFacts.model_validate(values)


def test_platform_registry_has_every_product_preset_and_dated_versions() -> None:
    presets = list_platform_presets()
    assert {preset.platform for preset in presets} == set(ReleasePlatform)
    assert len({preset.preset_id for preset in presets}) == len(presets)
    assert all(preset.official_sources for preset in presets)
    assert all("editorial overlay" in preset.safe_zone.basis for preset in presets)


def test_platform_registry_keeps_historical_versions_addressable() -> None:
    current = get_platform_preset(ReleasePlatform.GENERIC_VERTICAL)
    historical = current.model_copy(update={"version": "2026-08-14.1"})
    registry = PlatformPresetRegistry(
        (historical, current),
        {ReleasePlatform.GENERIC_VERTICAL: current.version},
    )

    assert registry.list_current() == (current,)
    assert registry.list_all() == (historical, current)
    assert registry.current_versions() == {ReleasePlatform.GENERIC_VERTICAL: current.version}
    assert registry.get(ReleasePlatform.GENERIC_VERTICAL) == current
    assert (
        registry.get(
            ReleasePlatform.GENERIC_VERTICAL,
            version=historical.version,
        )
        == historical
    )


def test_platform_registry_rejects_missing_or_duplicate_current_contracts() -> None:
    current = get_platform_preset(ReleasePlatform.GENERIC_VERTICAL)
    with pytest.raises(ValueError, match="unique"):
        PlatformPresetRegistry(
            (current, current),
            {ReleasePlatform.GENERIC_VERTICAL: current.version},
        )
    with pytest.raises(ValueError, match="does not exist"):
        PlatformPresetRegistry(
            (current,),
            {ReleasePlatform.GENERIC_VERTICAL: "2026-08-14.1"},
        )


def test_preflight_passes_portable_current_approved_release() -> None:
    result = evaluate_release_preflight(
        preset=get_platform_preset(ReleasePlatform.GENERIC_VERTICAL),
        media=_media(),
        editorial=_editorial(),
    )

    assert result.passed is True
    assert result.blocker_count == 0
    assert {check.code for check in result.checks} >= {
        "current_revision",
        "trusted_media",
        "human_checklist",
        "subtitle_readability",
        "account_policy",
    }


def test_preflight_blocks_stale_unapproved_and_incomplete_release() -> None:
    result = evaluate_release_preflight(
        preset=get_platform_preset(ReleasePlatform.GENERIC_VERTICAL),
        media=_media(available=False, trusted_render_contract=False),
        editorial=_editorial(
            current_revision=3,
            clip_review_approved=False,
            release_approval=ReleaseApprovalStatus.PENDING_REVIEW,
            checklist=_checklist(music_rights_confirmed=False),
        ),
    )

    blocked = {check.code for check in result.checks if check.outcome == "blocked"}
    assert result.passed is False
    assert blocked >= {
        "current_revision",
        "clip_review",
        "release_approval",
        "human_checklist",
        "trusted_media",
    }


def test_youtube_duration_is_hard_but_music_rights_is_visible_warning() -> None:
    preset = get_platform_preset(ReleasePlatform.YOUTUBE_SHORTS)
    too_long = evaluate_release_preflight(
        preset=preset,
        media=_media(duration_ms=180_001),
        editorial=_editorial(),
    )
    long_short = evaluate_release_preflight(
        preset=preset,
        media=_media(duration_ms=90_000),
        editorial=_editorial(),
    )

    assert next(check for check in too_long.checks if check.code == "duration").outcome == (
        "blocked"
    )
    assert (
        next(
            check for check in long_short.checks if check.code == "youtube_music_rights_over_60s"
        ).outcome
        == "warning"
    )


def test_clean_caption_mode_requires_srt_and_readability_is_not_hidden() -> None:
    result = evaluate_release_preflight(
        preset=get_platform_preset(ReleasePlatform.TIKTOK),
        media=_media(separate_subtitle_available=False),
        editorial=_editorial(
            captions=(CaptionCue(start_ms=0, end_ms=500, text="过短字幕"),),
        ),
    )

    assert next(check for check in result.checks if check.code == "separate_subtitles").outcome == (
        "blocked"
    )
    readability = next(check for check in result.checks if check.code == "subtitle_readability")
    assert readability.outcome == "warning"
    assert "0.6" in readability.message


def test_duplicate_content_is_visible_advice_and_never_a_hard_block() -> None:
    result = evaluate_release_preflight(
        preset=get_platform_preset(ReleasePlatform.DOUYIN),
        media=_media(),
        editorial=_editorial(
            duplicate_content_matches=(
                ReleaseDuplicateContentMatch(
                    reference_id="prior-release",
                    reference_label="xiaohongshu · 官方账号",
                    evidence_kind="published",
                    source_overlap_ratio=0.82,
                    text_similarity=0.76,
                ),
            )
        ),
    )

    duplicate = next(check for check in result.checks if check.code == "duplicate_content")
    assert duplicate.outcome == "warning"
    assert "源区间重叠 82%" in duplicate.message
    assert "文本相似 76%" in duplicate.message
    assert result.passed is True


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ReleaseItemStatus.DRAFT, ReleaseItemStatus.READY),
        (ReleaseItemStatus.READY, ReleaseItemStatus.SCHEDULED_EXTERNAL),
        (ReleaseItemStatus.SCHEDULED_EXTERNAL, ReleaseItemStatus.PUBLISHED),
        (ReleaseItemStatus.PUBLISHED, ReleaseItemStatus.WITHDRAWN),
    ],
)
def test_release_item_legal_transitions(
    current: ReleaseItemStatus,
    target: ReleaseItemStatus,
) -> None:
    transition_release_item(current, target)


def test_release_item_rejects_skip_to_published() -> None:
    with pytest.raises(ReleaseTransitionError):
        transition_release_item(ReleaseItemStatus.DRAFT, ReleaseItemStatus.PUBLISHED)


def test_release_approval_and_package_transitions_are_separate() -> None:
    transition_release_approval(
        ReleaseApprovalStatus.PENDING_REVIEW,
        ReleaseApprovalStatus.APPROVED,
    )
    transition_release_package(
        ReleasePackageStatus.QUEUED,
        ReleasePackageStatus.CREATING,
    )
    with pytest.raises(ReleaseTransitionError):
        transition_release_package(
            ReleasePackageStatus.SUCCEEDED,
            ReleasePackageStatus.QUEUED,
        )
