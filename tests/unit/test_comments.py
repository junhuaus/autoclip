from __future__ import annotations

import pytest
from pydantic import ValidationError

from liveclip.application.comments import (
    CreateClipCommentThread,
    ReplyToClipCommentThread,
    UpdateClipCommentThreadStatus,
)


def test_comment_commands_normalize_body_and_preserve_explicit_mentions() -> None:
    command = CreateClipCommentThread(
        expected_revision=3,
        clip_time_ms=12_540,
        body="  这里字幕需要精简  ",
        mentioned_user_ids=("reviewer-1", "editor-2"),
    )

    assert command.body == "这里字幕需要精简"
    assert command.mentioned_user_ids == ("reviewer-1", "editor-2")
    assert ReplyToClipCommentThread(body="收到", mentioned_user_ids=()).body == "收到"
    assert (
        UpdateClipCommentThreadStatus(
            expected_thread_version=2,
            status="resolved",
        ).status
        == "resolved"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"expected_revision": 1, "clip_time_ms": 0, "body": "   "},
        {
            "expected_revision": 1,
            "clip_time_ms": 0,
            "body": "批注",
            "mentioned_user_ids": ("same", "same"),
        },
        {"expected_revision": 0, "clip_time_ms": 0, "body": "批注"},
        {"expected_revision": 1, "clip_time_ms": -1, "body": "批注"},
    ],
)
def test_invalid_comment_commands_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CreateClipCommentThread.model_validate(payload)


def test_reply_is_append_only_and_does_not_require_a_stale_thread_version() -> None:
    reply = ReplyToClipCommentThread(body="并发回复不会互相覆盖")

    assert "expected_thread_version" not in reply.model_dump()
