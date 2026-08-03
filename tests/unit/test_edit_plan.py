import pytest
from pydantic import ValidationError

from liveclip.domain.edit_plan import (
    CaptionCue,
    CaptionTemplate,
    EditPlan,
    Effect,
    Layout,
    captions_to_srt,
    validate_caption_cues,
    validate_edit_plan_bounds,
)


def make_plan(**changes: object) -> EditPlan:
    payload: dict[str, object] = {
        "candidate_id": "candidate_1",
        "source_start_ms": 1_000,
        "source_end_ms": 32_000,
        "score": 88.0,
        "title": "一个完整的中文标题",
        "hook": "开场直接提出关键问题",
        "reason": "表达完整且信息密度高",
        "layout": Layout.VERTICAL_BLUR_BACKGROUND,
        "caption_template": CaptionTemplate.CLEAN_ZH_V1,
        "effect": Effect.NONE,
        "risk_flags": (),
        "prompt_version": "editing_v1",
        "model": "mock-llm-v1",
        "degraded": False,
    }
    payload.update(changes)
    return EditPlan.model_validate(payload)


def test_edit_plan_schema_is_closed_and_whitelisted() -> None:
    schema = EditPlan.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["$defs"]["Layout"]["enum"]) == {
        "vertical_blur_background",
        "center_crop",
    }

    with pytest.raises(ValidationError):
        make_plan(layout="model_chosen_filter", command="ffmpeg -i source")


def test_edit_plan_rejects_executable_content() -> None:
    with pytest.raises(ValidationError):
        make_plan(title="运行 ffmpeg -i /tmp/source.mp4")


@pytest.mark.parametrize(
    "unsafe_text",
    (
        "rm -rf data",
        "/home/user/a.mp4",
        "scale=540:960",
    ),
)
def test_edit_plan_rejects_bounded_safe_text_false_negatives(unsafe_text: str) -> None:
    with pytest.raises(ValidationError):
        make_plan(reason=unsafe_text)


def test_edit_plan_safe_text_accepts_normal_chinese_editorial_content() -> None:
    plan = make_plan(title="直播剪辑 A/B 测试: 第 1 集")
    assert plan.title == "直播剪辑 A/B 测试: 第 1 集"


def test_edit_plan_context_and_duration_bounds() -> None:
    plan = make_plan()
    validate_edit_plan_bounds(
        plan,
        source_duration_ms=60_000,
        minimum_duration_ms=30_000,
        maximum_duration_ms=90_000,
        allowed_start_ms=0,
        allowed_end_ms=40_000,
    )
    with pytest.raises(ValueError):
        validate_edit_plan_bounds(
            plan,
            source_duration_ms=60_000,
            minimum_duration_ms=40_000,
            maximum_duration_ms=90_000,
            allowed_start_ms=0,
            allowed_end_ms=40_000,
        )


def test_caption_cues_are_relative_and_render_valid_srt() -> None:
    cues = (
        CaptionCue(start_ms=0, end_ms=2_400, text="第一句"),
        CaptionCue(start_ms=2_400, end_ms=5_000, text="第二句"),
    )
    validate_caption_cues(cues, clip_duration_ms=5_000)
    srt = captions_to_srt(cues)
    assert "00:00:00,000 --> 00:00:02,400" in srt
    assert "第一句" in srt
