from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import pytest
from PIL import ImageFont

import liveclip.renderer.service as renderer_service
from liveclip.config.fonts import detect_chinese_font, font_supports_text
from liveclip.domain.edit_plan import (
    MAX_RENDER_OVERLAYS,
    TITLE_OVERLAY_COUNT,
    CaptionCue,
    CaptionTemplate,
    EditPlan,
    Effect,
    Layout,
    expand_caption_cues_for_display,
    validate_caption_cues,
)
from liveclip.domain.review import EditPlanRevision, RevisionOrigin
from liveclip.renderer.service import (
    RenderTextMode,
    display_caption_cues,
    render_revision_overlays_for_mode,
)
from liveclip.renderer.text import (
    TextOverlay,
    _wrap_text,
    normalize_display_text,
    render_caption_overlay,
)


def test_wrap_text_does_not_claim_truncation_only_because_space_is_trimmed() -> None:
    font = ImageFont.truetype(str(detect_chinese_font()), 32)
    value = "第二句字幕不会进入 FFmpeg 的可执行语法。"

    lines = _wrap_text(value, font=font, maximum_width=450, max_lines=2)

    assert not lines[-1].endswith("…")
    assert "FFmpeg" in "".join(lines)


def test_long_caption_is_time_split_without_losing_display_text() -> None:
    text = (
        "这是一个合法的长中文字幕，需要被确定性拆分成多个画面片段，"  # noqa: RUF001
        "而且任何一个汉字都不能静默丢失。"
    ) * 2
    cues = display_caption_cues((CaptionCue(start_ms=0, end_ms=8_000, text=text),))

    assert len(cues) > 1
    assert "".join(cue.text for cue in cues) == normalize_display_text(text, maximum_characters=120)
    assert cues[0].start_ms == 0
    assert cues[-1].end_ms == 8_000
    assert all(left.end_ms == right.start_ms for left, right in pairwise(cues))


def test_renderer_expansion_matches_domain_at_overlay_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cues = tuple(
        CaptionCue(
            start_ms=index * 1_500,
            end_ms=(index + 1) * 1_500,
            text=(str(index % 10) + "字幕" * 53 + "字"),
        )
        for index in range(21)
    )

    validate_caption_cues(cues, clip_duration_ms=31_500)
    domain_cues = expand_caption_cues_for_display(cues)
    renderer_cues = display_caption_cues(cues)
    rendered_caption_text: list[str] = []

    def fake_title_overlay(
        *,
        output_path: Path,
        width: int,
        height: int,
        text: str,
        start_ms: int,
        end_ms: int,
        font_path: Path | None = None,
    ) -> TextOverlay:
        del width, height, text, font_path
        return TextOverlay(output_path, start_ms, end_ms, (1, 1, 10, 10), "title")

    def fake_caption_overlay(
        *,
        output_path: Path,
        width: int,
        height: int,
        text: str,
        start_ms: int,
        end_ms: int,
        font_path: Path | None = None,
    ) -> TextOverlay:
        del width, height, font_path
        rendered_caption_text.append(text)
        return TextOverlay(output_path, start_ms, end_ms, (1, 20, 10, 30), "caption")

    monkeypatch.setattr(renderer_service, "render_title_overlay", fake_title_overlay)
    monkeypatch.setattr(renderer_service, "render_caption_overlay", fake_caption_overlay)
    revision = EditPlanRevision(
        clip_id="clip_near_limit",
        revision=1,
        parent_revision=None,
        origin=RevisionOrigin.HUMAN,
        plan=EditPlan(
            candidate_id="candidate_near_limit",
            source_start_ms=0,
            source_end_ms=31_500,
            score=90,
            title="字幕预算临界值",
            hook="验证领域与渲染器使用相同规则",
            reason="临界值合法时渲染展开不得额外拒绝",
            layout=Layout.CENTER_CROP,
            caption_template=CaptionTemplate.CLEAN_ZH_V1,
            effect=Effect.NONE,
            risk_flags=(),
            prompt_version="editing_v1",
            model="mock-llm-v1",
            degraded=False,
        ),
        captions=cues,
        created_at=datetime.now(UTC),
    )
    overlays = renderer_service.render_revision_overlays(
        revision=revision,
        output_dir=tmp_path,
        width=540,
        height=960,
    )

    assert renderer_cues == domain_cues
    assert len(renderer_cues) + TITLE_OVERLAY_COUNT == MAX_RENDER_OVERLAYS
    assert len(overlays) == MAX_RENDER_OVERLAYS
    assert rendered_caption_text == [cue.text for cue in domain_cues]


def test_clean_review_mode_materializes_no_title_or_caption_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = EditPlanRevision(
        clip_id="clip_clean_review",
        revision=1,
        origin=RevisionOrigin.AI,
        plan=EditPlan(
            candidate_id="candidate_clean_review",
            source_start_ms=0,
            source_end_ms=4_000,
            score=88,
            title="这段标题只作为审核元数据",
            hook="三秒内提出明确问题",
            reason="观点完整且适合独立传播",
            layout=Layout.CENTER_CROP,
            caption_template=CaptionTemplate.CLEAN_ZH_V1,
            effect=Effect.NONE,
            risk_flags=(),
            prompt_version="editing_v1",
            model="mock-llm-v1",
            degraded=False,
        ),
        captions=(CaptionCue(start_ms=0, end_ms=4_000, text="字幕同样保持为独立数据"),),
        created_at=datetime.now(UTC),
    )

    def forbidden_overlay(**_kwargs: object) -> TextOverlay:
        raise AssertionError("clean review video must not rasterize editorial text")

    monkeypatch.setattr(renderer_service, "render_title_overlay", forbidden_overlay)
    monkeypatch.setattr(renderer_service, "render_caption_overlay", forbidden_overlay)
    output_dir = tmp_path / "clean-overlays"

    overlays = render_revision_overlays_for_mode(
        revision=revision,
        output_dir=output_dir,
        width=540,
        height=960,
        text_mode=RenderTextMode.NONE,
    )

    assert overlays == ()
    assert not output_dir.exists()


def test_wrap_text_rejects_overflow_instead_of_adding_ellipsis() -> None:
    font = ImageFont.truetype(str(detect_chinese_font()), 32)
    with pytest.raises(ValueError, match="overlay bounds"):
        _wrap_text("超长字幕" * 80, font=font, maximum_width=120, max_lines=2)


def test_detected_font_has_required_chinese_glyph_coverage() -> None:
    font_path = detect_chinese_font()

    assert font_supports_text(
        font_path,
        "中文直播高光字幕标题，。！？",  # noqa: RUF001
    )
    assert not font_supports_text(font_path, "🧬")


def test_overlay_rejects_text_without_configured_glyph_coverage(tmp_path: Path) -> None:
    output = tmp_path / "unsupported.png"

    with pytest.raises(ValueError, match="covers all requested text glyphs"):
        render_caption_overlay(
            output_path=output,
            width=540,
            height=960,
            text="字幕🧬",
            start_ms=0,
            end_ms=2_000,
        )

    assert not output.exists()


def test_overlay_refuses_symbolic_link_output_endpoint(tmp_path: Path) -> None:
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside-must-remain-unchanged")
    output = tmp_path / "caption.png"
    output.symlink_to(outside)

    with pytest.raises(ValueError, match="published safely"):
        render_caption_overlay(
            output_path=output,
            width=540,
            height=960,
            text="安全字幕",
            start_ms=0,
            end_ms=2_000,
        )

    assert outside.read_bytes() == b"outside-must-remain-unchanged"
