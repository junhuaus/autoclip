from datetime import UTC, datetime
from pathlib import Path

from liveclip.domain.edit_plan import CaptionCue, CaptionTemplate, EditPlan, Effect, Layout
from liveclip.domain.review import (
    EditPlanRevision,
    RenderKind,
    RenderRecord,
    RenderStatus,
    ReviewStatus,
    RevisionOrigin,
    add_render,
    decide_clip,
    revise_clip,
    start_clip_lifecycle,
)
from liveclip.media.fingerprint import stream_sha256


def make_plan(*, title: str = "初始标题") -> EditPlan:
    return EditPlan(
        candidate_id="candidate_1",
        source_start_ms=1_000,
        source_end_ms=31_000,
        score=90.0,
        title=title,
        hook="开场直接给出结论",
        reason="表达完整且信息密度高",
        layout=Layout.VERTICAL_BLUR_BACKGROUND,
        caption_template=CaptionTemplate.CLEAN_ZH_V1,
        effect=Effect.NONE,
        risk_flags=(),
        prompt_version="editing_v1",
        model="mock-llm-v1",
        degraded=False,
    )


def test_new_revision_invalidates_approval_and_stales_old_render(tmp_path: Path) -> None:
    moment = datetime(2026, 8, 3, tzinfo=UTC)
    captions = (CaptionCue(start_ms=0, end_ms=2_000, text="第一句"),)
    revision = EditPlanRevision(
        clip_id="clip_1",
        revision=1,
        origin=RevisionOrigin.AI,
        plan=make_plan(),
        captions=captions,
        created_at=moment,
    )
    lifecycle = start_clip_lifecycle(revision)
    video = tmp_path / "proxy.mp4"
    video.write_bytes(b"proxy" * 100)
    lifecycle = add_render(
        lifecycle,
        RenderRecord(
            render_id="proxy_r1",
            revision=1,
            kind=RenderKind.PROXY,
            status=RenderStatus.SUCCEEDED,
            path=video,
            sha256=stream_sha256(video),
        ),
    )
    lifecycle = decide_clip(lifecycle, status=ReviewStatus.APPROVED, decided_at=moment)
    assert lifecycle.review_status == ReviewStatus.APPROVED

    revised = revise_clip(
        lifecycle,
        plan=make_plan(title="人工修改后的标题"),
        captions=captions,
        created_at=moment,
    )

    assert revised.current_revision == 2
    assert revised.review_status == ReviewStatus.PENDING_REVIEW
    assert revised.renders[0].status == RenderStatus.STALE
    assert revised.revisions[1].parent_revision == 1
    assert revised.revisions[1].origin == RevisionOrigin.HUMAN
