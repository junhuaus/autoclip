"""B1 selection evidence on migrated disposable SQLite with actual queue leases."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from threading import Barrier, Event

import pytest
from pydantic import ValidationError
from sqlalchemy import insert, select, update
from test_completion_identity import NOW, OWNER, Fixture, context, fixture, revoke

from liveclip.application.completion import (
    CompletionConflict,
    CompletionOptions,
    CompletionResourceNotFound,
    CompletionSelectedClip,
    CompletionSelectionCheckpoint,
    CompletionSelectionSubmission,
)
from liveclip.application.completion_runner import ReconciliationResult
from liveclip.application.reviewing import ReviewCommand
from liveclip.db import completion_repository as repository_module
from liveclip.db.base import new_id
from liveclip.db.completion_repository import SqlAlchemyCompletionRepository
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    CandidateClipRow,
    CompletionIntentRow,
    DeliveryRow,
    EditPlanRevisionRow,
    IdempotencyRecordRow,
    ProjectRow,
    ReviewDecisionRow,
    SourceMediaRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.db.review_repository import SqlAlchemyReviewRepository
from liveclip.domain.completion import CompletionSelectionPolicy
from liveclip.domain.edit_plan import CaptionTemplate, EditPlan, Effect, Layout
from liveclip.domain.state_transitions import ReviewStatus

pytestmark = pytest.mark.integration
# Reuse A's migrated database fixture, not its test cases.
__all__ = ["fixture"]


def ready(fixture: Fixture, *, manual=False, count=2, include_zip=True):
    goal = fixture.create(
        options=CompletionOptions(
            include_zip=include_zip,
            selection_policy=(
                CompletionSelectionPolicy.MANUAL if manual else CompletionSelectionPolicy.DEFAULT
            ),
        )
    )
    fixture.run_status(goal, "completed")
    clips = []
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            insert(SourceMediaRow).values(
                id=new_id(),
                project_id=goal.project_id,
                resolved_path=str(fixture.root / "synthetic.mp4"),
                filename="synthetic.mp4",
                sha256="a" * 64,
                size_bytes=1000,
                mtime_ns=1,
                duration_ms=20000,
                width=1920,
                height=1080,
                video_codec="h264",
                audio_codec="aac",
                frame_rate="30",
                probe_json={},
            )
        )
        for index in range(count):
            clip_id, revision_id = new_id(), new_id()
            clips.append(clip_id)
            plan = EditPlan(
                candidate_id=clip_id,
                source_start_ms=2000,
                source_end_ms=10000,
                score=88,
                title="测试标题",
                hook="完整开场",
                reason="表达完整",
                layout=Layout.CENTER_CROP,
                caption_template=CaptionTemplate.CLEAN_ZH_V1,
                effect=Effect.NONE,
                risk_flags=(),
                prompt_version="editing_v1",
                model="mock-llm-v1",
                degraded=True,
            )
            connection.execute(
                insert(CandidateClipRow).values(
                    id=clip_id,
                    project_id=goal.project_id,
                    pipeline_run_id=goal.run_id,
                    candidate_key=f"candidate-{index}",
                    source_start_ms=2000,
                    source_end_ms=10000,
                    allowed_start_ms=0,
                    allowed_end_ms=20000,
                    transcript_text="完整中文转写",
                    rule_score=88,
                    reasons_json=[],
                    segment_ids_json=[],
                    current_revision=1,
                    rank=index + 1,
                    selected_for_review=True,
                )
            )
            connection.execute(
                insert(EditPlanRevisionRow).values(
                    id=revision_id,
                    candidate_clip_id=clip_id,
                    revision=1,
                    origin="deterministic",
                    source_start_ms=2000,
                    source_end_ms=10000,
                    score=88,
                    title=plan.title,
                    hook=plan.hook,
                    reason=plan.reason,
                    layout=plan.layout.value,
                    caption_template=plan.caption_template.value,
                    effect=plan.effect.value,
                    risk_flags_json=[],
                    prompt_version=plan.prompt_version,
                    model=plan.model,
                    degraded=True,
                    plan_json=plan.model_dump(mode="json"),
                )
            )
    return goal, tuple(sorted(clips))


def snapshot(fixture):
    return tuple(
        fixture.rows(model)
        for model in (
            CompletionIntentRow,
            TaskRow,
            TaskAttemptRow,
            ReviewDecisionRow,
            DeliveryRow,
            IdempotencyRecordRow,
        )
    )


def checkpoint(fixture):
    raw = fixture.rows(CompletionIntentRow)[0]["selection_checkpoint_json"]
    return CompletionSelectionCheckpoint.model_validate_json(json.dumps(raw))


def submit(fixture, goal, clips=(), *, version=None):
    current = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    request = CompletionSelectionSubmission(
        expected_version=current.version if version is None else version,
        selected=tuple(CompletionSelectedClip(clip_id=c, expected_revision=1) for c in clips),
    )
    return fixture.service.submit_selection(goal.intent_id, request, actor_user_id=OWNER)


def review(fixture, clip, status=ReviewStatus.REJECTED):
    return SqlAlchemyReviewRepository(fixture.engine).review_clip(
        clip,
        ReviewCommand(
            expected_revision=1,
            status=status,
            reason="Human exclusion" if status == ReviewStatus.REJECTED else None,
        ),
    )


def test_default_checkpoint_roundtrip_and_missing_master_parking(fixture):
    goal, clips = ready(fixture)
    assert fixture.observe() == ReconciliationResult.DEFERRED
    saved = checkpoint(fixture)
    assert saved.intent_id == goal.intent_id and saved.run_id == goal.run_id
    assert saved.generation == goal.generation and saved.mode == CompletionSelectionPolicy.DEFAULT
    assert saved.action_key == f"completion-selection:{goal.intent_id}"
    assert tuple(c.clip_id for c in saved.selected) == clips
    assert all(c.edit_plan_revision == 1 for c in saved.selected)
    decisions = fixture.rows(ReviewDecisionRow)
    for seconds, expected in (
        (60, ReconciliationResult.NEEDS_ACTION),
        (120, ReconciliationResult.IDLE),
    ):
        assert fixture.observe(NOW + timedelta(seconds=seconds)) == expected
        assert checkpoint(fixture) == saved
        assert fixture.rows(ReviewDecisionRow) == decisions
    task = fixture.task(goal)
    assert task["status"] == "waiting"
    assert task["retry_count"] == 0 and task["attempt_count"] == 2
    assert {a["outcome"] for a in fixture.rows(TaskAttemptRow)} == {"deferred"}
    assert fixture.rows(DeliveryRow) == []
    assert not (fixture.root / "synthetic.mp4").exists()
    assert list(fixture.root.rglob("*.zip")) == []


@pytest.mark.parametrize("count", [0, 2])
def test_empty_default_outcomes_without_delivery(fixture, count):
    goal, clips = ready(fixture, count=count)
    for clip in clips:
        review(fixture, clip)
    before = fixture.rows(ReviewDecisionRow)
    assert fixture.observe() == ReconciliationResult.PROCESSED
    current = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    assert current.outcome.value == ("no_selected_clips" if count else "no_eligible_clips")
    assert fixture.task(goal)["status"] == "succeeded"
    assert fixture.rows(TaskAttemptRow)[0]["outcome"] == "succeeded"
    assert fixture.rows(ReviewDecisionRow) == before
    assert fixture.rows(DeliveryRow) == []


@pytest.mark.parametrize("empty", [False, True])
def test_manual_wait_exact_submission_and_response_loss(fixture, empty, monkeypatch):
    goal, clips = ready(fixture, manual=True)
    assert fixture.observe() == ReconciliationResult.NEEDS_ACTION
    waiting = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    task = fixture.task(goal)
    assert waiting.status.value == "waiting_selection" and not waiting.selection_submitted
    before = snapshot(fixture)
    for seconds in (60, 120, 3600):
        assert fixture.observe(NOW + timedelta(seconds=seconds)) == ReconciliationResult.IDLE
    assert snapshot(fixture) == before
    original = repository_module.begin_immediate

    @contextmanager
    def lose_response(engine):
        with original(engine) as connection:
            yield connection
        raise ConnectionError("response lost after commit")

    chosen = () if empty else clips[:1]
    with monkeypatch.context() as patch:
        patch.setattr(repository_module, "begin_immediate", lose_response)
        with pytest.raises(ConnectionError):
            submit(fixture, goal, chosen, version=waiting.version)
    committed = snapshot(fixture)
    fixture.engine.dispose(close=True)
    replay = submit(fixture, goal, chosen, version=waiting.version)
    assert replay.selection_submitted and replay.status.value == "queued"
    assert snapshot(fixture) == committed
    assert fixture.task(goal)["id"] == task["id"]
    assert fixture.task(goal)["attempt_count"] == task["attempt_count"]
    assert tuple(c.clip_id for c in checkpoint(fixture).selected) == chosen
    assert fixture.observe() == (
        ReconciliationResult.PROCESSED if empty else ReconciliationResult.NEEDS_ACTION
    )
    after_poll = snapshot(fixture)
    submit(fixture, goal, chosen, version=waiting.version)
    assert snapshot(fixture) == after_poll
    assert fixture.rows(DeliveryRow) == []
    if empty:
        assert (
            fixture.service.get(goal.intent_id, actor_user_id=OWNER).outcome.value
            == "no_selected_clips"
        )


def test_submitted_empty_checkpoint_survives_disappearing_eligibility(fixture):
    goal, clips = ready(fixture, manual=True)
    assert fixture.observe() == ReconciliationResult.NEEDS_ACTION
    waiting = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    submitted = submit(fixture, goal, version=waiting.version)
    saved = checkpoint(fixture)
    decisions = fixture.rows(ReviewDecisionRow)
    task = fixture.task(goal)
    assert saved.selected == () and submitted.selection_submitted
    assert task["status"] == "queued" and task["attempt_count"] == 1
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(CandidateClipRow)
            .where(CandidateClipRow.id.in_(clips))
            .values(selected_for_review=False)
        )

    assert fixture.observe() == ReconciliationResult.PROCESSED
    current = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    assert current.outcome.value == "no_selected_clips"
    assert current.version == submitted.version + 1 and current.selection_submitted
    assert checkpoint(fixture) == saved
    assert fixture.rows(ReviewDecisionRow) == decisions
    finished = fixture.task(goal)
    assert finished["id"] == task["id"] and finished["status"] == "succeeded"
    assert finished["attempt_count"] == 2 and finished["retry_count"] == 0
    assert [a["outcome"] for a in fixture.rows(TaskAttemptRow)].count("succeeded") == 1
    before_replay = snapshot(fixture)
    submit(fixture, goal, version=waiting.version)
    assert snapshot(fixture) == before_replay
    assert fixture.rows(DeliveryRow) == []
    assert list(fixture.root.rglob("*.zip")) == []


@pytest.mark.parametrize(
    "bad", ["unknown", "revision", "duplicate", "version", "generation", "cross-run"]
)
def test_manual_conflicts_leave_no_partial_effects(fixture, bad):
    goal, clips = ready(fixture, manual=True)
    fixture.observe()
    current = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    selected = [CompletionSelectedClip(clip_id=clips[0], expected_revision=1)]
    if bad == "unknown":
        selected.append(CompletionSelectedClip(clip_id=new_id(), expected_revision=1))
    elif bad == "revision":
        selected.append(CompletionSelectedClip(clip_id=clips[1], expected_revision=2))
    elif bad == "duplicate":
        selected += selected
    elif bad == "generation":
        with begin_immediate(fixture.engine) as connection:
            connection.execute(
                update(ProjectRow)
                .where(ProjectRow.id == goal.project_id)
                .values(current_generation=2)
            )
    elif bad == "cross-run":
        other = fixture.create(idempotency=context("other"))
        with begin_immediate(fixture.engine) as connection:
            connection.execute(
                update(CandidateClipRow)
                .where(CandidateClipRow.id == clips[0])
                .values(pipeline_run_id=other.run_id)
            )
    before = snapshot(fixture)
    with pytest.raises((CompletionConflict, ValidationError)):
        request = CompletionSelectionSubmission(
            expected_version=current.version + (1 if bad == "version" else 0),
            selected=tuple(selected),
        )
        fixture.service.submit_selection(goal.intent_id, request, actor_user_id=OWNER)
    assert snapshot(fixture) == before


@pytest.mark.parametrize("mode", ["disabled", "removed", "archived", "downgraded"])
@pytest.mark.parametrize("replay", [False, True])
def test_current_authority_before_manual_effect_and_replay(fixture, mode, replay):
    goal, clips = ready(fixture, manual=True)
    fixture.observe()
    version = fixture.service.get(goal.intent_id, actor_user_id=OWNER).version
    if replay:
        submit(fixture, goal, clips, version=version)
    with begin_immediate(fixture.engine) as connection:
        revoke(connection, goal, mode)
    before = snapshot(fixture)
    request = CompletionSelectionSubmission(
        expected_version=version,
        selected=tuple(CompletionSelectedClip(clip_id=c, expected_revision=1) for c in clips),
    )
    with pytest.raises(CompletionResourceNotFound):
        fixture.repository.submit_selection(goal.intent_id, request, actor_user_id=OWNER)
    assert snapshot(fixture) == before


@pytest.mark.parametrize("failure", ["expired", "forged", "final-fence", "clock", "cas"])
def test_failed_fences_roll_back_entire_selection(fixture, monkeypatch, failure):
    goal, _ = ready(fixture)
    lease = fixture.queue.claim_completion(worker_id="worker", now=NOW)
    assert lease is not None
    # An active delivery proves review invalidation also rolls back.
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            insert(DeliveryRow).values(
                id=new_id(),
                project_id=goal.project_id,
                expected_generation=1,
                expected_revision_epoch=0,
                status="queued",
                include_zip=True,
                version=1,
                snapshot_fingerprint="a" * 64,
                directory_relative_path="deliveries/test",
            )
        )
    before = snapshot(fixture)
    at = NOW + timedelta(seconds=30) if failure == "expired" else NOW
    if failure == "forged":
        lease = replace(lease, lease_token="f" * 64)
    elif failure == "final-fence":

        def reject_final(connection, *args, **kwargs):
            assert connection.scalar(select(ReviewDecisionRow.id)) is not None
            assert connection.scalar(select(DeliveryRow.status)) == "failed"
            return False

        monkeypatch.setattr(repository_module, "finish_completion_attempt", reject_final)
    elif failure == "clock":
        times = iter((NOW, NOW + timedelta(seconds=30)))
        monkeypatch.setattr(repository_module, "_instant", lambda _: next(times))
    elif failure == "cas":

        def fail(*args, **kwargs):
            raise CompletionConflict("injected CAS failure")

        monkeypatch.setattr(SqlAlchemyCompletionRepository, "_update", fail)
    if failure == "cas":
        with pytest.raises(CompletionConflict):
            fixture.repository.reconcile_completion(lease, now=at)
    else:
        assert (
            fixture.repository.reconcile_completion(lease, now=at)
            == ReconciliationResult.LOST_LEASE
        )
    assert snapshot(fixture) == before


@pytest.mark.parametrize("change", ["rejection", "revision", "eligibility"])
def test_saved_selection_cannot_follow_live_drift(fixture, change):
    _, clips = ready(fixture)
    fixture.observe()
    if change == "rejection":
        # Force a later decision independent of the wall clock used by review UI.
        with begin_immediate(fixture.engine) as connection:
            connection.execute(
                insert(ReviewDecisionRow).values(
                    id=new_id(),
                    candidate_clip_id=clips[0],
                    edit_plan_revision_id=checkpoint(fixture).selected[0].edit_plan_revision_id,
                    status="rejected",
                    rejection_reason="Human exclusion",
                    decided_at=NOW + timedelta(seconds=1),
                )
            )
    else:
        with begin_immediate(fixture.engine) as connection:
            connection.execute(
                update(CandidateClipRow)
                .where(CandidateClipRow.id == clips[0])
                .values(
                    **(
                        {"current_revision": 2}
                        if change == "revision"
                        else {"selected_for_review": False}
                    )
                )
            )
    saved = checkpoint(fixture)
    decisions = fixture.rows(ReviewDecisionRow)
    assert fixture.observe(NOW + timedelta(seconds=60)) == ReconciliationResult.NEEDS_ACTION
    assert fixture.rows(CompletionIntentRow)[0]["blocking_code"] == "SELECTION_CHANGED"
    assert checkpoint(fixture) == saved
    assert fixture.rows(ReviewDecisionRow) == decisions
    assert fixture.rows(DeliveryRow) == []


def test_later_unrelated_approval_cannot_expand_checkpoint(fixture):
    _, clips = ready(fixture)
    review(fixture, clips[1])
    fixture.observe()
    saved = checkpoint(fixture)
    review(fixture, clips[1], ReviewStatus.APPROVED)
    assert fixture.observe(NOW + timedelta(seconds=60)) == ReconciliationResult.NEEDS_ACTION
    assert fixture.rows(CompletionIntentRow)[0]["blocking_code"] == "SELECTION_CHANGED"
    assert checkpoint(fixture) == saved
    assert tuple(c.clip_id for c in saved.selected) == clips[:1]


@pytest.mark.parametrize("race", ["human", "expiry", "revocation", "generation"])
def test_writer_lock_interleavings(fixture, monkeypatch, race):
    goal, clips = ready(fixture)
    lease = fixture.queue.claim_completion(worker_id="worker", now=NOW)
    assert lease is not None
    waiting = Event()
    clock = NOW

    @contextmanager
    def wait_for_writer(engine):
        waiting.set()
        with begin_immediate(engine) as connection:
            yield connection

    monkeypatch.setattr(repository_module, "begin_immediate", wait_for_writer)
    monkeypatch.setattr(repository_module, "_instant", lambda _: clock)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with begin_immediate(fixture.engine) as connection:
            future = executor.submit(fixture.repository.reconcile_completion, lease)
            assert waiting.wait(5)
            if race == "human":
                revision = connection.scalar(
                    select(EditPlanRevisionRow.id).where(
                        EditPlanRevisionRow.candidate_clip_id == clips[0]
                    )
                )
                connection.execute(
                    insert(ReviewDecisionRow).values(
                        id=new_id(),
                        candidate_clip_id=clips[0],
                        edit_plan_revision_id=revision,
                        status="rejected",
                        rejection_reason="Human exclusion",
                        decided_at=NOW,
                    )
                )
            elif race == "expiry":
                clock += timedelta(seconds=30)
            elif race == "revocation":
                revoke(connection, goal, "downgraded")
            else:
                connection.execute(
                    update(ProjectRow)
                    .where(ProjectRow.id == goal.project_id)
                    .values(current_generation=2)
                )
        result = future.result(timeout=5)
    if race == "human":
        assert result == ReconciliationResult.DEFERRED
        assert tuple(c.clip_id for c in checkpoint(fixture).selected) == clips[1:]
        assert len(fixture.rows(ReviewDecisionRow)) == 2
    elif race == "expiry":
        assert result == ReconciliationResult.LOST_LEASE
        assert fixture.rows(ReviewDecisionRow) == []
        assert fixture.rows(CompletionIntentRow)[0]["selection_checkpoint_json"] is None
    else:
        assert result == ReconciliationResult.NEEDS_ACTION
        assert fixture.rows(ReviewDecisionRow) == []


def test_simultaneous_claims_have_one_owner_and_one_batch(fixture):
    ready(fixture)
    barrier = Barrier(2)

    def claim(worker):
        barrier.wait(timeout=5)
        return fixture.queue.claim_completion(worker_id=worker, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as executor:
        leases = list(executor.map(claim, ("one", "two")))
    owned = [lease for lease in leases if lease is not None]
    assert len(owned) == 1
    assert (
        fixture.repository.reconcile_completion(owned[0], now=NOW) == ReconciliationResult.DEFERRED
    )
    before = snapshot(fixture)
    assert (
        fixture.repository.reconcile_completion(owned[0], now=NOW)
        == ReconciliationResult.LOST_LEASE
    )
    assert snapshot(fixture) == before


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_processing_blocker_parks_without_resetting_budget(fixture, status):
    goal, _ = ready(fixture)
    fixture.run_status(goal, status)
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(TaskRow).where(TaskRow.target_id == goal.intent_id).values(retry_count=2)
        )
    assert fixture.observe() == ReconciliationResult.NEEDS_ACTION
    current = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    assert current.blocking_code == f"PROCESSING_{status.upper()}"
    assert fixture.task(goal)["retry_count"] == 2
    before = snapshot(fixture)
    assert fixture.observe(NOW + timedelta(days=1)) == ReconciliationResult.IDLE
    assert snapshot(fixture) == before


@pytest.mark.parametrize("mode", ["disabled", "removed", "archived", "downgraded"])
@pytest.mark.parametrize("replay", [False, True])
def test_default_current_authority_before_effect_and_replay(fixture, mode, replay):
    goal, _ = ready(fixture)
    if replay:
        fixture.observe()
    with begin_immediate(fixture.engine) as connection:
        revoke(connection, goal, mode)
    decisions = fixture.rows(ReviewDecisionRow)
    saved = fixture.rows(CompletionIntentRow)[0]["selection_checkpoint_json"]
    assert fixture.observe(NOW + timedelta(seconds=60)) == ReconciliationResult.NEEDS_ACTION
    assert fixture.rows(ReviewDecisionRow) == decisions
    assert fixture.rows(CompletionIntentRow)[0]["selection_checkpoint_json"] == saved
    assert fixture.task(goal)["status"] == "waiting"


@pytest.mark.parametrize("fault", ["cas", "record", "wake"])
def test_manual_failure_rolls_back_decisions_submission_and_wake(fixture, monkeypatch, fault):
    goal, clips = ready(fixture, manual=True)
    fixture.observe()
    before = snapshot(fixture)

    def fail(*args, **kwargs):
        raise RuntimeError("injected submission failure")

    if fault == "cas":
        monkeypatch.setattr(SqlAlchemyCompletionRepository, "_update", fail)
    elif fault == "record":
        monkeypatch.setattr(repository_module, "record_idempotent_resource", fail)
    else:
        monkeypatch.setattr(repository_module, "wake_completion_task", lambda *a, **k: False)
    with pytest.raises((RuntimeError, CompletionConflict)):
        submit(fixture, goal, clips[:1])
    assert snapshot(fixture) == before


@pytest.mark.parametrize("change", ["payload", "version"])
def test_manual_committed_action_rejects_conflicting_retry(fixture, change):
    goal, clips = ready(fixture, manual=True)
    fixture.observe()
    version = fixture.service.get(goal.intent_id, actor_user_id=OWNER).version
    submit(fixture, goal, clips[:1], version=version)
    before = snapshot(fixture)
    with pytest.raises(CompletionConflict):
        submit(
            fixture,
            goal,
            clips if change == "payload" else clips[:1],
            version=version + (1 if change == "version" else 0),
        )
    assert snapshot(fixture) == before


def test_checkpoint_capacity_overflow_rolls_back_all_approvals(fixture):
    ready(fixture, count=101)
    lease = fixture.queue.claim_completion(worker_id="worker", now=NOW)
    assert lease is not None
    before = snapshot(fixture)
    with pytest.raises(CompletionConflict):
        fixture.repository.reconcile_completion(lease, now=NOW)
    assert snapshot(fixture) == before


@pytest.mark.parametrize("field", ["intent_id", "run_id", "generation", "action_key", "mode"])
def test_checkpoint_identity_tampering_fails_closed(fixture, field):
    goal, _ = ready(fixture)
    fixture.observe()
    raw = checkpoint(fixture).model_dump(mode="json")
    raw[field] = {"generation": 2, "mode": "manual", "action_key": "other"}.get(field, new_id())
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(CompletionIntentRow)
            .where(CompletionIntentRow.id == goal.intent_id)
            .values(selection_checkpoint_json=raw)
        )
    lease = fixture.queue.claim_completion(worker_id="worker", now=NOW + timedelta(seconds=60))
    assert lease is not None
    before = fixture.rows(CompletionIntentRow)[0]["selection_checkpoint_json"]
    assert fixture.repository.reconcile_completion(lease, now=NOW + timedelta(seconds=60)) == (
        ReconciliationResult.NEEDS_ACTION
    )
    after = fixture.rows(CompletionIntentRow)[0]
    assert after["selection_checkpoint_json"] == before
    assert after["delivery_id"] is None and after["delivery_action_key"] is None
    assert after["blocking_code"] == "SELECTION_CHANGED"
