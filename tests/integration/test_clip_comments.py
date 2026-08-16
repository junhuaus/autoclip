from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine

from liveclip.api.app import create_app
from liveclip.application.authorization import ProjectActionDenied
from liveclip.application.comments import (
    ClipCommentService,
    CommentConflict,
    CommentResourceNotFound,
    CreateClipCommentThread,
    ReplyToClipCommentThread,
    UpdateClipCommentThreadStatus,
)
from liveclip.application.idempotency import (
    IdempotencyConflict,
    IdempotencyContext,
    build_idempotency_context,
)
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.db.base import Base
from liveclip.db.comment_repository import SqlAlchemyClipCommentRepository
from liveclip.db.engine import begin_immediate, create_sqlite_engine
from liveclip.db.models import (
    AuditEventRow,
    CandidateClipRow,
    ClipCommentMentionRow,
    ClipCommentRow,
    ClipCommentThreadRow,
    EditPlanRevisionRow,
    IdempotencyRecordRow,
    PipelineRunRow,
    ProjectMemberRow,
    ProjectRow,
    ReviewDecisionRow,
    WorkspaceUserRow,
)
from liveclip.db.storage_repository import _project_resource_ids
from liveclip.db.workspace_repository import WorkspacePermissionDenied
from liveclip.domain.state_transitions import PipelineRunStatus

pytestmark = pytest.mark.integration


@pytest.fixture
def comment_context(
    tmp_path: Path,
) -> Iterator[tuple[Engine, ClipCommentService, dict[str, str]]]:
    engine = create_sqlite_engine(tmp_path / "clip-comments.sqlite3")
    Base.metadata.create_all(engine)
    ids = {
        "project": "project0000000000000000000000001",
        "run": "run00000000000000000000000000001",
        "clip": "clip0000000000000000000000000001",
        "revision_1": "revision00000000000000000000001",
        "owner": "owner000000000000000000000000001",
        "editor": "editor00000000000000000000000001",
        "reviewer": "reviewer0000000000000000000000001",
        "viewer": "viewer00000000000000000000000001",
        "outsider": "outsider000000000000000000000001",
    }
    with engine.begin() as connection:
        for key, username, display_name in (
            ("owner", "owner", "负责人"),
            ("editor", "editor", "林编辑"),
            ("reviewer", "reviewer", "王审核"),
            ("viewer", "viewer", "只读成员"),
            ("outsider", "outsider", "项目外成员"),
        ):
            connection.execute(
                insert(WorkspaceUserRow).values(
                    id=ids[key],
                    username=username,
                    display_name=display_name,
                    system_role="member",
                    is_active=True,
                )
            )
        connection.execute(
            insert(ProjectRow).values(
                id=ids["project"],
                name="多人批注项目",
                owner_id=ids["owner"],
                visibility="private",
                lifecycle="editorial_review",
                source_request_path="/allowed/source.mp4",
                current_generation=1,
                current_pipeline_run_id=ids["run"],
                revision_epoch=0,
            )
        )
        for index, (key, role) in enumerate(
            (
                ("owner", "owner"),
                ("editor", "editor"),
                ("reviewer", "reviewer"),
                ("viewer", "viewer"),
            ),
            start=1,
        ):
            connection.execute(
                insert(ProjectMemberRow).values(
                    id=f"member{index:026d}",
                    project_id=ids["project"],
                    user_id=ids[key],
                    role=role,
                )
            )
        connection.execute(
            insert(PipelineRunRow).values(
                id=ids["run"],
                project_id=ids["project"],
                generation=1,
                status=PipelineRunStatus.COMPLETED.value,
                config_json={"schema_version": "test"},
                config_fingerprint="a" * 64,
                progress=100,
                manual_retry_count=0,
            )
        )
        connection.execute(
            insert(CandidateClipRow).values(
                id=ids["clip"],
                project_id=ids["project"],
                pipeline_run_id=ids["run"],
                candidate_key="candidate-1",
                source_start_ms=2_000,
                source_end_ms=10_000,
                allowed_start_ms=0,
                allowed_end_ms=15_000,
                transcript_text="多人协作批注测试",
                context_before="",
                context_after="",
                rule_score=88,
                reasons_json=["完整"],
                segment_ids_json=[],
                current_revision=1,
                rank=1,
                selected_for_review=True,
            )
        )
        _insert_revision(
            connection,
            revision_id=ids["revision_1"],
            clip_id=ids["clip"],
            revision=1,
            parent_revision=None,
            start_ms=2_000,
            end_ms=10_000,
        )
    service = ClipCommentService(SqlAlchemyClipCommentRepository(engine))
    try:
        yield engine, service, ids
    finally:
        engine.dispose(close=True)


def test_revision_timecode_threads_mentions_concurrent_replies_and_resolution(
    comment_context: tuple[Engine, ClipCommentService, dict[str, str]],
) -> None:
    engine, service, ids = comment_context
    create_key = _idempotency(
        "create-thread",
        "POST:/clips/:clip_id/comment-threads",
        {"clip_id": ids["clip"], "body": "这里字幕需要精简"},
    )
    created = service.create_thread(
        ids["clip"],
        CreateClipCommentThread(
            expected_revision=1,
            clip_time_ms=2_000,
            body="  这里字幕需要精简  ",
            mentioned_user_ids=(ids["reviewer"],),
        ),
        acting_user_id=ids["owner"],
        correlation_id="request-create",
        idempotency=create_key,
    )

    assert created.edit_plan_revision == 1
    assert created.source_time_ms == 4_000
    assert created.clip_time_ms == 2_000
    assert created.current_clip_time_ms == 2_000
    assert created.allowed_actions == ("reply", "resolve")
    assert created.comments[0].body == "这里字幕需要精简"
    assert created.comments[0].mentions[0].display_name == "王审核"

    replay = service.create_thread(
        ids["clip"],
        CreateClipCommentThread(
            expected_revision=1,
            clip_time_ms=2_000,
            body="这里字幕需要精简",
            mentioned_user_ids=(ids["reviewer"],),
        ),
        acting_user_id=ids["owner"],
        idempotency=create_key,
    )
    assert replay.thread_id == created.thread_id

    first_reply = service.reply(
        created.thread_id,
        ReplyToClipCommentThread(body="我来调整", mentioned_user_ids=(ids["owner"],)),
        acting_user_id=ids["editor"],
        idempotency=_idempotency(
            "reply-editor",
            "POST:/comment-threads/:thread_id/replies",
            {"thread_id": created.thread_id, "body": "我来调整"},
        ),
    )
    second_reply = service.reply(
        created.thread_id,
        ReplyToClipCommentThread(body="调整后请提醒我"),
        acting_user_id=ids["reviewer"],
    )
    assert first_reply.version == 2
    assert second_reply.version == 3
    assert [message.body for message in second_reply.comments] == [
        "这里字幕需要精简",
        "我来调整",
        "调整后请提醒我",
    ]

    with pytest.raises(CommentConflict, match="changed"):
        service.update_status(
            created.thread_id,
            UpdateClipCommentThreadStatus(expected_thread_version=2, status="resolved"),
            acting_user_id=ids["owner"],
        )
    resolved = service.update_status(
        created.thread_id,
        UpdateClipCommentThreadStatus(expected_thread_version=3, status="resolved"),
        acting_user_id=ids["owner"],
    )
    assert resolved.status == "resolved"
    assert resolved.version == 4
    assert resolved.allowed_actions == ("reopen",)
    assert resolved.resolved_by is not None
    assert resolved.resolved_by.username == "owner"
    with pytest.raises(CommentConflict, match="reopened"):
        service.reply(
            created.thread_id,
            ReplyToClipCommentThread(body="关闭后不能直接回复"),
            acting_user_id=ids["editor"],
        )
    reopened = service.update_status(
        created.thread_id,
        UpdateClipCommentThreadStatus(expected_thread_version=4, status="open"),
        acting_user_id=ids["reviewer"],
    )
    assert reopened.version == 5
    assert reopened.resolved_by is None

    with engine.begin() as connection:
        revision_2 = "revision00000000000000000000002"
        _insert_revision(
            connection,
            revision_id=revision_2,
            clip_id=ids["clip"],
            revision=2,
            parent_revision=1,
            start_ms=3_000,
            end_ms=10_000,
        )
        connection.execute(
            update(CandidateClipRow)
            .where(CandidateClipRow.id == ids["clip"])
            .values(current_revision=2)
        )

    current_only = service.list_threads(
        ids["clip"],
        acting_user_id=ids["owner"],
        revision_scope="current",
    )
    history = service.list_threads(
        ids["clip"],
        acting_user_id=ids["owner"],
        revision_scope="all",
    )
    assert current_only.total_count == 0
    assert history.total_count == 1
    assert history.threads[0].is_current_revision is False
    assert history.threads[0].is_current_generation is True
    assert history.threads[0].source_time_ms == 4_000
    assert history.threads[0].clip_time_ms == 2_000
    assert history.threads[0].current_clip_time_ms == 1_000

    with pytest.raises(CommentConflict, match="revision changed"):
        service.create_thread(
            ids["clip"],
            CreateClipCommentThread(expected_revision=1, clip_time_ms=1_000, body="旧 revision"),
            acting_user_id=ids["editor"],
        )
    with pytest.raises(CommentConflict, match="outside"):
        service.create_thread(
            ids["clip"],
            CreateClipCommentThread(expected_revision=2, clip_time_ms=7_001, body="越界"),
            acting_user_id=ids["editor"],
        )

    with engine.connect() as connection:
        assert connection.scalar(select(func.count(ClipCommentThreadRow.id))) == 1
        assert connection.scalar(select(func.count(ClipCommentRow.id))) == 3
        assert connection.scalar(select(func.count(ClipCommentMentionRow.id))) == 2
        assert connection.scalar(select(func.count(IdempotencyRecordRow.id))) == 2
        assert connection.scalar(select(func.count(ReviewDecisionRow.id))) == 0
        project_resource_ids = _project_resource_ids(connection, ids["project"])
        assert created.thread_id in project_resource_ids
        assert {
            str(value)
            for value in connection.scalars(
                select(ClipCommentRow.id).where(ClipCommentRow.thread_id == created.thread_id)
            )
        }.issubset(project_resource_ids)
        audits = tuple(
            connection.execute(
                select(
                    AuditEventRow.action,
                    AuditEventRow.before_json,
                    AuditEventRow.after_json,
                ).where(AuditEventRow.project_id == ids["project"])
            )
        )
        assert [str(row.action) for row in audits] == [
            "comment.thread_created",
            "comment.reply_created",
            "comment.reply_created",
            "comment.thread_resolved",
            "comment.thread_reopened",
        ]
        assert audits[3].after_json["actor_identity"] == {
            "user_id": ids["owner"],
            "username": "owner",
            "display_name": "负责人",
        }
        assert audits[4].after_json["actor_identity"] == {
            "user_id": ids["reviewer"],
            "username": "reviewer",
            "display_name": "王审核",
        }
        audit_payload = json.dumps(
            [(row.before_json, row.after_json) for row in audits],
            ensure_ascii=False,
        )
        assert "字幕需要精简" not in audit_payload
        assert "我来调整" not in audit_payload


def test_comment_permissions_archive_mentions_and_identity_snapshots(
    comment_context: tuple[Engine, ClipCommentService, dict[str, str]],
) -> None:
    engine, service, ids = comment_context
    created = service.create_thread(
        ids["clip"],
        CreateClipCommentThread(
            expected_revision=1,
            clip_time_ms=0,
            body="开场画面需要复核",
            mentioned_user_ids=(ids["reviewer"],),
        ),
        acting_user_id=ids["reviewer"],
    )
    viewer_list = service.list_threads(
        ids["clip"],
        acting_user_id=ids["viewer"],
        revision_scope="all",
    )
    assert viewer_list.threads[0].allowed_actions == ()
    with pytest.raises(ProjectActionDenied):
        service.create_thread(
            ids["clip"],
            CreateClipCommentThread(expected_revision=1, clip_time_ms=1, body="只读越权"),
            acting_user_id=ids["viewer"],
        )
    with pytest.raises(CommentResourceNotFound):
        service.list_threads(
            ids["clip"],
            acting_user_id=ids["outsider"],
            revision_scope="all",
        )
    with pytest.raises(CommentConflict, match="active explicit project members"):
        service.reply(
            created.thread_id,
            ReplyToClipCommentThread(
                body="不能跨项目提醒",
                mentioned_user_ids=(ids["outsider"],),
            ),
            acting_user_id=ids["editor"],
        )

    with engine.begin() as connection:
        connection.execute(
            update(WorkspaceUserRow)
            .where(WorkspaceUserRow.id == ids["reviewer"])
            .values(username="reviewer-renamed", display_name="审核新名称")
        )
    historical = service.get_thread(created.thread_id, acting_user_id=ids["owner"])
    assert historical.created_by.username == "reviewer"
    assert historical.created_by.display_name == "王审核"
    assert historical.comments[0].mentions[0].username == "reviewer"

    with engine.begin() as connection:
        connection.execute(
            update(ProjectRow)
            .where(ProjectRow.id == ids["project"])
            .values(lifecycle="archived", lifecycle_before_archive="editorial_review")
        )
    archived = service.list_threads(
        ids["clip"],
        acting_user_id=ids["owner"],
        revision_scope="all",
    )
    assert archived.threads[0].allowed_actions == ()
    with pytest.raises(ProjectActionDenied, match="read-only"):
        service.reply(
            created.thread_id,
            ReplyToClipCommentThread(body="归档后禁止写入"),
            acting_user_id=ids["owner"],
        )

    with engine.begin() as connection:
        connection.execute(
            update(ProjectRow)
            .where(ProjectRow.id == ids["project"])
            .values(lifecycle="editorial_review", lifecycle_before_archive=None)
        )
        connection.execute(
            update(WorkspaceUserRow)
            .where(WorkspaceUserRow.id == ids["editor"])
            .values(is_active=False)
        )
    with pytest.raises(WorkspacePermissionDenied):
        service.reply(
            created.thread_id,
            ReplyToClipCommentThread(body="停用账号不能写入"),
            acting_user_id=ids["editor"],
        )
    with engine.connect() as connection:
        assert connection.scalar(select(func.count(ClipCommentRow.id))) == 1
        assert connection.scalar(select(func.count(AuditEventRow.id))) == 1


def test_comment_idempotency_key_cannot_be_reused_for_different_payload(
    comment_context: tuple[Engine, ClipCommentService, dict[str, str]],
) -> None:
    _engine, service, ids = comment_context
    key = _idempotency(
        "same-key",
        "POST:/clips/:clip_id/comment-threads",
        {"body": "第一条"},
    )
    service.create_thread(
        ids["clip"],
        CreateClipCommentThread(expected_revision=1, clip_time_ms=0, body="第一条"),
        acting_user_id=ids["owner"],
        idempotency=key,
    )
    with pytest.raises(IdempotencyConflict):
        service.create_thread(
            ids["clip"],
            CreateClipCommentThread(expected_revision=1, clip_time_ms=1, body="第二条"),
            acting_user_id=ids["owner"],
            idempotency=_idempotency(
                "same-key",
                "POST:/clips/:clip_id/comment-threads",
                {"body": "第二条"},
            ),
        )


def test_concurrent_replies_append_without_lost_messages(
    comment_context: tuple[Engine, ClipCommentService, dict[str, str]],
) -> None:
    engine, service, ids = comment_context
    created = service.create_thread(
        ids["clip"],
        CreateClipCommentThread(
            expected_revision=1,
            clip_time_ms=1_000,
            body="请两位编辑一起确认",
        ),
        acting_user_id=ids["owner"],
    )
    start = Barrier(3)

    def reply(user_id: str, body: str) -> int:
        start.wait(timeout=5)
        return service.reply(
            created.thread_id,
            ReplyToClipCommentThread(body=body),
            acting_user_id=user_id,
        ).version

    with ThreadPoolExecutor(max_workers=2) as executor:
        editor_reply = executor.submit(reply, ids["editor"], "编辑回复")
        reviewer_reply = executor.submit(reply, ids["reviewer"], "审核回复")
        start.wait(timeout=5)
        versions = {editor_reply.result(timeout=10), reviewer_reply.result(timeout=10)}

    assert versions == {2, 3}
    final = service.get_thread(created.thread_id, acting_user_id=ids["owner"])
    assert len(final.comments) == 3
    assert {message.body for message in final.comments[1:]} == {"编辑回复", "审核回复"}
    with engine.connect() as connection:
        assert tuple(
            connection.scalars(
                select(ClipCommentRow.sequence)
                .where(ClipCommentRow.thread_id == created.thread_id)
                .order_by(ClipCommentRow.sequence)
            )
        ) == (1, 2, 3)


def test_reply_and_resolve_race_commits_exactly_one_consistent_winner(
    comment_context: tuple[Engine, ClipCommentService, dict[str, str]],
) -> None:
    engine, service, ids = comment_context
    created = service.create_thread(
        ids["clip"],
        CreateClipCommentThread(
            expected_revision=1,
            clip_time_ms=1_000,
            body="回复和解决并发",
        ),
        acting_user_id=ids["owner"],
    )
    start = Barrier(3)

    def reply() -> str:
        start.wait(timeout=5)
        try:
            service.reply(
                created.thread_id,
                ReplyToClipCommentThread(body="并发回复"),
                acting_user_id=ids["editor"],
            )
        except CommentConflict:
            return "reply_conflict"
        return "reply_succeeded"

    def resolve() -> str:
        start.wait(timeout=5)
        try:
            service.update_status(
                created.thread_id,
                UpdateClipCommentThreadStatus(
                    expected_thread_version=1,
                    status="resolved",
                ),
                acting_user_id=ids["reviewer"],
            )
        except CommentConflict:
            return "resolve_conflict"
        return "resolve_succeeded"

    with ThreadPoolExecutor(max_workers=2) as executor:
        reply_result = executor.submit(reply)
        resolve_result = executor.submit(resolve)
        start.wait(timeout=5)
        outcomes = {reply_result.result(timeout=10), resolve_result.result(timeout=10)}

    final = service.get_thread(created.thread_id, acting_user_id=ids["owner"])
    assert final.version == 2
    if "reply_succeeded" in outcomes:
        assert outcomes == {"reply_succeeded", "resolve_conflict"}
        assert final.status == "open"
        assert [message.body for message in final.comments] == [
            "回复和解决并发",
            "并发回复",
        ]
        expected_actions = ["comment.thread_created", "comment.reply_created"]
    else:
        assert outcomes == {"resolve_succeeded", "reply_conflict"}
        assert final.status == "resolved"
        assert [message.body for message in final.comments] == ["回复和解决并发"]
        expected_actions = ["comment.thread_created", "comment.thread_resolved"]
    with engine.connect() as connection:
        assert (
            list(
                connection.scalars(
                    select(AuditEventRow.action)
                    .where(AuditEventRow.project_id == ids["project"])
                    .order_by(AuditEventRow.created_at, AuditEventRow.id)
                )
            )
            == expected_actions
        )


def test_reply_and_status_idempotency_replay_are_exactly_once(
    comment_context: tuple[Engine, ClipCommentService, dict[str, str]],
) -> None:
    engine, service, ids = comment_context
    created = service.create_thread(
        ids["clip"],
        CreateClipCommentThread(expected_revision=1, clip_time_ms=0, body="幂等批注"),
        acting_user_id=ids["owner"],
    )
    reply_command = ReplyToClipCommentThread(body="只追加一次")
    reply_key = _idempotency(
        "reply-exactly-once",
        "POST:/comment-threads/:thread_id/replies",
        {"thread_id": created.thread_id, "body": "只追加一次"},
    )
    first_reply = service.reply(
        created.thread_id,
        reply_command,
        acting_user_id=ids["editor"],
        idempotency=reply_key,
    )
    replayed_reply = service.reply(
        created.thread_id,
        reply_command,
        acting_user_id=ids["editor"],
        idempotency=reply_key,
    )
    assert first_reply.version == replayed_reply.version == 2
    assert len(replayed_reply.comments) == 2

    status_command = UpdateClipCommentThreadStatus(
        expected_thread_version=2,
        status="resolved",
    )
    status_key = _idempotency(
        "status-exactly-once",
        "POST:/comment-threads/:thread_id/status",
        {"thread_id": created.thread_id, "status": "resolved"},
    )
    first_status = service.update_status(
        created.thread_id,
        status_command,
        acting_user_id=ids["reviewer"],
        idempotency=status_key,
    )
    replayed_status = service.update_status(
        created.thread_id,
        status_command,
        acting_user_id=ids["reviewer"],
        idempotency=status_key,
    )
    assert first_status.version == replayed_status.version == 3
    assert replayed_status.status == "resolved"
    with engine.connect() as connection:
        assert connection.scalar(select(func.count(ClipCommentRow.id))) == 2
        assert connection.scalar(select(func.count(AuditEventRow.id))) == 3
        assert connection.scalar(select(func.count(IdempotencyRecordRow.id))) == 2


def test_membership_revocation_is_rechecked_after_waiting_for_the_writer_lock(
    comment_context: tuple[Engine, ClipCommentService, dict[str, str]],
) -> None:
    engine, service, ids = comment_context
    created = service.create_thread(
        ids["clip"],
        CreateClipCommentThread(expected_revision=1, clip_time_ms=0, body="撤权竞态"),
        acting_user_id=ids["owner"],
    )
    revocation_staged = Event()
    allow_commit = Event()

    def revoke_membership() -> None:
        with begin_immediate(engine) as connection:
            connection.execute(
                delete(ProjectMemberRow).where(
                    ProjectMemberRow.project_id == ids["project"],
                    ProjectMemberRow.user_id == ids["editor"],
                )
            )
            revocation_staged.set()
            assert allow_commit.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as executor:
        revocation = executor.submit(revoke_membership)
        assert revocation_staged.wait(timeout=5)
        attempted_reply = executor.submit(
            service.reply,
            created.thread_id,
            ReplyToClipCommentThread(body="撤权后不得写入"),
            acting_user_id=ids["editor"],
        )
        allow_commit.set()
        revocation.result(timeout=10)
        with pytest.raises(CommentResourceNotFound):
            attempted_reply.result(timeout=10)

    with engine.connect() as connection:
        assert connection.scalar(select(func.count(ClipCommentRow.id))) == 1
        assert connection.scalar(select(func.count(AuditEventRow.id))) == 1


def test_comment_thread_filters_and_bounded_pagination(
    comment_context: tuple[Engine, ClipCommentService, dict[str, str]],
) -> None:
    _engine, service, ids = comment_context
    created = []
    for index in range(3):
        created.append(
            service.create_thread(
                ids["clip"],
                CreateClipCommentThread(
                    expected_revision=1,
                    clip_time_ms=index * 1_000,
                    body=f"批注 {index + 1}",
                ),
                acting_user_id=ids["editor"],
            )
        )
    service.update_status(
        created[1].thread_id,
        UpdateClipCommentThreadStatus(expected_thread_version=1, status="resolved"),
        acting_user_id=ids["reviewer"],
    )

    first_page = service.list_threads(
        ids["clip"],
        acting_user_id=ids["viewer"],
        revision_scope="current",
        status_filter="all",
        limit=2,
    )
    second_page = service.list_threads(
        ids["clip"],
        acting_user_id=ids["viewer"],
        revision_scope="current",
        status_filter="all",
        limit=2,
        offset=2,
    )
    open_threads = service.list_threads(
        ids["clip"],
        acting_user_id=ids["viewer"],
        status_filter="open",
    )
    resolved_threads = service.list_threads(
        ids["clip"],
        acting_user_id=ids["viewer"],
        status_filter="resolved",
    )

    assert first_page.total_count == 3
    assert first_page.next_offset == 2
    assert len(first_page.threads) == 2
    assert second_page.total_count == 3
    assert second_page.next_offset is None
    assert len(second_page.threads) == 1
    assert open_threads.total_count == 2
    assert all(thread.status == "open" for thread in open_threads.threads)
    assert resolved_threads.total_count == 1
    assert resolved_threads.threads[0].thread_id == created[1].thread_id


def test_comment_api_authorization_idempotency_and_stable_conflicts(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    media_root = tmp_path / "media"
    media_root.mkdir()
    settings = Settings(
        data_dir=tmp_path / "api-projects",
        allowed_media_roots_raw=str(media_root),
        api_token=SecretStr("owner-token-secret-2026"),
        workspace_tokens_raw=json.dumps(
            {
                "editor": "editor-token-secret-2026",
                "reviewer": "reviewer-token-secret-2026",
                "viewer": "viewer-token-secret-2026",
                "outsider": "outsider-token-secret-2026",
            }
        ),
        ai_provider="mock",
        _env_file=None,
    )
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    users = {
        username: runtime.workspace_service.get_user_by_username(username)
        for username in ("local-admin", "editor", "reviewer", "viewer", "outsider")
    }
    project_id = "projectapi0000000000000000000001"
    run_id = "runapi00000000000000000000000001"
    clip_id = "clipapi0000000000000000000000001"
    revision_id = "revisionapi000000000000000000001"
    with runtime.engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id=project_id,
                name="批注 API 项目",
                owner_id=users["local-admin"].user_id,
                visibility="private",
                lifecycle="editorial_review",
                source_request_path="/allowed/source.mp4",
                current_generation=1,
                current_pipeline_run_id=run_id,
                revision_epoch=0,
            )
        )
        for index, (username, role) in enumerate(
            (
                ("local-admin", "owner"),
                ("editor", "editor"),
                ("reviewer", "reviewer"),
                ("viewer", "viewer"),
            ),
            start=1,
        ):
            connection.execute(
                insert(ProjectMemberRow).values(
                    id=f"apimember{index:023d}",
                    project_id=project_id,
                    user_id=users[username].user_id,
                    role=role,
                )
            )
        connection.execute(
            insert(PipelineRunRow).values(
                id=run_id,
                project_id=project_id,
                generation=1,
                status=PipelineRunStatus.COMPLETED.value,
                config_json={"schema_version": "test"},
                config_fingerprint="b" * 64,
                progress=100,
                manual_retry_count=0,
            )
        )
        connection.execute(
            insert(CandidateClipRow).values(
                id=clip_id,
                project_id=project_id,
                pipeline_run_id=run_id,
                candidate_key="api-candidate",
                source_start_ms=1_000,
                source_end_ms=9_000,
                allowed_start_ms=0,
                allowed_end_ms=10_000,
                transcript_text="批注 API 测试",
                context_before="",
                context_after="",
                rule_score=90,
                reasons_json=["完整"],
                segment_ids_json=[],
                current_revision=1,
                rank=1,
                selected_for_review=True,
            )
        )
        _insert_revision(
            connection,
            revision_id=revision_id,
            clip_id=clip_id,
            revision=1,
            parent_revision=None,
            start_ms=1_000,
            end_ms=9_000,
        )
    app = create_app(settings, runtime=runtime, project_root=project_root)
    auth = {
        username: {"Authorization": f"Bearer {token}"}
        for username, token in (
            ("owner", "owner-token-secret-2026"),
            ("editor", "editor-token-secret-2026"),
            ("reviewer", "reviewer-token-secret-2026"),
            ("viewer", "viewer-token-secret-2026"),
            ("outsider", "outsider-token-secret-2026"),
        )
    }
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            created = client.post(
                f"/api/v1/clips/{clip_id}/comment-threads",
                headers={**auth["owner"], "Idempotency-Key": "api-create-thread"},
                json={
                    "expected_revision": 1,
                    "clip_time_ms": 2_500,
                    "body": "这里需要补一个转场",
                    "mentioned_user_ids": [users["editor"].user_id],
                },
            )
            assert created.status_code == 201, created.text
            thread = created.json()
            thread_id = thread["thread_id"]
            assert created.headers["Location"] == f"/api/v1/comment-threads/{thread_id}"
            assert thread["source_time_ms"] == 3_500
            assert thread["allowed_actions"] == ["reply", "resolve"]

            replay = client.post(
                f"/api/v1/clips/{clip_id}/comment-threads",
                headers={**auth["owner"], "Idempotency-Key": "api-create-thread"},
                json={
                    "expected_revision": 1,
                    "clip_time_ms": 2_500,
                    "body": "这里需要补一个转场",
                    "mentioned_user_ids": [users["editor"].user_id],
                },
            )
            assert replay.status_code == 201
            assert replay.json()["thread_id"] == thread_id

            replied = client.post(
                f"/api/v1/comment-threads/{thread_id}/replies",
                headers={**auth["editor"], "Idempotency-Key": "api-reply"},
                json={"body": "已收到,会在这里调整", "mentioned_user_ids": []},
            )
            assert replied.status_code == 201, replied.text
            assert replied.json()["version"] == 2
            assert len(replied.json()["comments"]) == 2

            viewer = client.get(
                f"/api/v1/comment-threads/{thread_id}",
                headers=auth["viewer"],
            )
            assert viewer.status_code == 200
            assert viewer.json()["allowed_actions"] == []
            denied = client.post(
                f"/api/v1/comment-threads/{thread_id}/replies",
                headers=auth["viewer"],
                json={"body": "越权回复"},
            )
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "PROJECT_ACTION_DENIED"
            hidden = client.get(
                f"/api/v1/comment-threads/{thread_id}",
                headers=auth["outsider"],
            )
            assert hidden.status_code == 404

            stale = client.post(
                f"/api/v1/comment-threads/{thread_id}/status",
                headers=auth["reviewer"],
                json={"expected_thread_version": 1, "status": "resolved"},
            )
            assert stale.status_code == 409
            assert stale.json()["error"]["code"] == "STATE_CONFLICT"
            resolved = client.post(
                f"/api/v1/comment-threads/{thread_id}/status",
                headers={**auth["reviewer"], "Idempotency-Key": "api-resolve"},
                json={"expected_thread_version": 2, "status": "resolved"},
            )
            assert resolved.status_code == 200
            assert resolved.json()["status"] == "resolved"

            listed = client.get(
                f"/api/v1/clips/{clip_id}/comment-threads",
                headers=auth["owner"],
                params={"revision": "all", "status": "all", "limit": 1, "offset": 0},
            )
            assert listed.status_code == 200
            assert listed.json()["total_count"] == 1
            assert listed.json()["next_offset"] is None

            invalid = client.post(
                f"/api/v1/clips/{clip_id}/comment-threads",
                headers=auth["owner"],
                json={
                    "expected_revision": 1,
                    "clip_time_ms": 0,
                    "body": "批注",
                    "command": "rm -rf /",
                },
            )
            assert invalid.status_code == 422
            assert invalid.json()["error"]["code"] == "INVALID_REQUEST"
    finally:
        runtime.close()


def _insert_revision(
    connection: Connection,
    *,
    revision_id: str,
    clip_id: str,
    revision: int,
    parent_revision: int | None,
    start_ms: int,
    end_ms: int,
) -> None:
    connection.execute(
        insert(EditPlanRevisionRow).values(
            id=revision_id,
            candidate_clip_id=clip_id,
            revision=revision,
            parent_revision=parent_revision,
            origin="human" if revision > 1 else "deterministic",
            source_start_ms=start_ms,
            source_end_ms=end_ms,
            score=88,
            title=f"高光 revision {revision}",
            hook="关键语句",
            reason="完整",
            layout="center_crop",
            caption_template="clean_zh_v1",
            effect="none",
            risk_flags_json=[],
            prompt_version="editing_v1",
            model="mock",
            degraded=True,
            plan_json={"schema_version": "1"},
        )
    )


def _idempotency(key: str, operation: str, payload: object) -> IdempotencyContext:
    return build_idempotency_context(
        raw_key=key,
        caller_scope="user:owner",
        operation_scope=operation,
        request_payload=payload,
    )
