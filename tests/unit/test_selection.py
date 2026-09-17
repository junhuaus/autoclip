from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import liveclip.cli.app as cli_module
from liveclip.application.clips import ClipSummary
from liveclip.application.reviewing import BatchReviewCommand
from liveclip.application.selection import (
    SelectionConflict,
    SelectionMode,
    SelectionResult,
    SelectionService,
)
from liveclip.domain.state_transitions import RenderStatus, ReviewStatus


def _clip(
    index: int,
    *,
    status: ReviewStatus,
    risk_flags: tuple[str, ...] = (),
) -> ClipSummary:
    return ClipSummary(
        clip_id=f"clip_{index}",
        candidate_key=f"candidate_{index}",
        edit_plan_revision=1,
        source_start_ms=index * 10_000,
        source_end_ms=(index + 1) * 10_000,
        score=90 - index,
        title=f"候选 {index}",
        hook=f"高光 {index}",
        reason="完整主题",
        risk_flags=risk_flags,
        captions=(),
        keywords=(),
        review_status=status,
        proxy_status=RenderStatus.SUCCEEDED,
        proxy_asset_id=f"asset_{index}",
        allowed_actions=("review_clip",),
    )


class _SelectionHarness:
    def __init__(self, clips: tuple[ClipSummary, ...]) -> None:
        self.clips = clips
        self.commands: list[BatchReviewCommand] = []

    def list_project_clips(self, _project_id: str) -> tuple[ClipSummary, ...]:
        return self.clips

    def review_clips_batch(
        self,
        _project_id: str,
        command: BatchReviewCommand,
    ) -> tuple[object, ...]:
        self.commands.append(command)
        decisions = {item.clip_id: item for item in command.items}
        self.clips = tuple(
            clip.model_copy(update={"review_status": decisions[clip.clip_id].status})
            if clip.clip_id in decisions
            else clip
            for clip in self.clips
        )
        return ()


def _service(harness: _SelectionHarness) -> SelectionService:
    return SelectionService(harness, harness)  # type: ignore[arg-type]


def test_default_selection_selects_new_candidates_and_preserves_prior_exclusion() -> None:
    harness = _SelectionHarness(
        (
            _clip(1, status=ReviewStatus.PENDING_REVIEW),
            _clip(2, status=ReviewStatus.REJECTED),
        )
    )

    result = _service(harness).select("project", mode=SelectionMode.DEFAULT)

    assert result.selected_clip_ids == ("clip_1",)
    assert result.excluded_clip_ids == ("clip_2",)
    assert result.unchanged_clip_ids == ()
    assert tuple(item.clip_id for item in harness.commands[0].items) == ("clip_1",)


def test_default_selection_includes_manual_review_clips() -> None:
    harness = _SelectionHarness(
        (
            _clip(1, status=ReviewStatus.PENDING_REVIEW),
            _clip(
                2,
                status=ReviewStatus.PENDING_REVIEW,
                risk_flags=("manual_review", "music_rights"),
            ),
        )
    )

    default_result = _service(harness).select("project", mode=SelectionMode.DEFAULT)

    assert default_result.selected_clip_ids == ("clip_1", "clip_2")
    assert default_result.unchanged_clip_ids == ()
    assert tuple(item.clip_id for item in harness.commands[0].items) == (
        "clip_1",
        "clip_2",
    )


def test_manual_selection_selects_named_clips_and_excludes_every_other_candidate() -> None:
    harness = _SelectionHarness(
        tuple(_clip(index, status=ReviewStatus.PENDING_REVIEW) for index in range(1, 4))
    )

    result = _service(harness).select(
        "project",
        mode=SelectionMode.MANUAL,
        selected_clip_ids=("clip_3", "clip_1", "clip_3"),
    )

    assert result.selected_clip_ids == ("clip_1", "clip_3")
    assert result.excluded_clip_ids == ("clip_2",)
    command = harness.commands[0]
    assert [item.status for item in command.items] == [
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
        ReviewStatus.APPROVED,
    ]
    assert command.items[1].reason == "Not selected by the user"


def test_selection_rejects_unknown_manual_clip_and_explicit_default_ids() -> None:
    service = _service(_SelectionHarness((_clip(1, status=ReviewStatus.PENDING_REVIEW),)))

    with pytest.raises(SelectionConflict, match="unknown clip ID"):
        service.select(
            "project",
            mode=SelectionMode.MANUAL,
            selected_clip_ids=("unknown",),
        )

    with pytest.raises(SelectionConflict, match="does not accept explicit"):
        service.select(
            "project",
            mode=SelectionMode.DEFAULT,
            selected_clip_ids=("clip_1",),
        )


def test_manual_cli_selection_accepts_numbers_ids_deduplication_and_none() -> None:
    clip_ids = ("clip_a", "clip_b", "clip_c")

    assert cli_module._resolve_manual_selection("3,clip_a,3", clip_ids=clip_ids) == (
        "clip_c",
        "clip_a",
    )
    assert cli_module._resolve_manual_selection("none", clip_ids=clip_ids) == ()
    with pytest.raises(ValueError, match="outside"):
        cli_module._resolve_manual_selection("4", clip_ids=clip_ids)


def test_select_cli_routes_numbered_manual_selection_without_packaging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = tuple(_clip(index, status=ReviewStatus.PENDING_REVIEW) for index in range(1, 4))
    calls: list[tuple[str, SelectionMode, tuple[str, ...]]] = []

    class SelectionService:
        def select(
            self,
            project_id: str,
            *,
            mode: SelectionMode,
            selected_clip_ids: tuple[str, ...],
        ) -> SelectionResult:
            calls.append((project_id, mode, selected_clip_ids))
            return SelectionResult(
                project_id=project_id,
                mode=mode,
                candidate_count=3,
                selected_clip_ids=selected_clip_ids,
                excluded_clip_ids=("clip_2",),
                unchanged_clip_ids=(),
            )

    runtime = SimpleNamespace(
        clip_query_service=SimpleNamespace(
            list_project_clips=lambda _project_id: candidates,
        ),
        selection_service=SelectionService(),
    )

    @contextmanager
    def open_runtime(_settings: object):
        yield runtime

    monkeypatch.setattr(cli_module, "get_settings", lambda: object())
    monkeypatch.setattr(
        cli_module,
        "LiveClipRuntime",
        SimpleNamespace(open=open_runtime),
    )

    result = CliRunner().invoke(
        cli_module.app,
        ["select", "project", "--mode", "manual", "--clips", "3,1", "--no-package"],
    )

    assert result.exit_code == 0, result.output
    assert "已选择     2" in result.output
    assert calls == [
        ("project", SelectionMode.MANUAL, ("clip_3", "clip_1")),
    ]
