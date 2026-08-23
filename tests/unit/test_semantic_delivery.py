from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from liveclip.media.models import SourceMediaMetadata
from liveclip.renderer.ffmpeg import RenderRequest, RenderResult
from liveclip.services import semantic_delivery
from liveclip.services.semantic_delivery import (
    OfflineSemanticReview,
    SemanticDeliveryError,
    render_reviewed_semantic_delivery,
)


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    source = tmp_path / "input" / "source.ts"
    source.parent.mkdir()
    source.write_bytes(b"source-media")
    transcript = tmp_path / "transcript.srt"
    transcript.write_text(
        "\n\n".join(
            (
                "1\n00:00:00,000 --> 00:00:20,000\n开场",
                "2\n00:00:20,000 --> 00:00:50,000\n直接问题",
                "3\n00:00:50,000 --> 00:01:10,000\n回答和结论",
                "4\n00:01:10,000 --> 00:02:00,000\n另一个话题",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    plan = tmp_path / "final-validated.json"
    plan.write_text(
        json.dumps(
            {
                "selected": [
                    {
                        "clip": {
                            "clip_id": "clip_01",
                            "title": "原标题",
                            "hook": "直接问题的答案是什么?",
                            "review_reason": "片段包含直接问题、回答和结论。",
                            "risks": [
                                {
                                    "type": "general_health_warning",
                                    "severity": "low",
                                    "reason": "一般提醒",
                                    "source_cue_ids": [2],
                                }
                            ],
                            "start_cue_id": 1,
                            "end_cue_id": 3,
                        },
                        "final_score": 88,
                    }
                ],
                "manual_review": [
                    {
                        "clip": {
                            "clip_id": "clip_02",
                            "title": "不交付的话题",
                            "start_cue_id": 3,
                            "end_cue_id": 4,
                        },
                        "final_score": 80,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    plan_sha256 = hashlib.sha256(plan.read_bytes()).hexdigest()
    review = tmp_path / "offline-review.json"
    review.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "plan_sha256": plan_sha256,
                "reviewer": "offline_agent",
                "selections": [
                    {
                        "clip_id": "clip_01",
                        "start_cue_id": 2,
                        "end_cue_id": 3,
                        "title": "复核后的标题",
                        "reason": "删除不必要的承接开头。",
                    }
                ],
                "rejected": [{"clip_id": "clip_02", "reason": "价值不足。"}],
                "notes": ["边界调整是复核数据, 不是生产规则。"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return source, transcript, plan, review, tmp_path / "output"


def _source_metadata(source: Path) -> SourceMediaMetadata:
    metadata = source.stat()
    return SourceMediaMetadata(
        resolved_path=source.resolve(),
        filename=source.name,
        size_bytes=metadata.st_size,
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        duration_ms=120_000,
        format_name="mpegts",
        video_stream_index=0,
        video_codec="h264",
        video_width=1088,
        video_height=1920,
        video_frame_rate=25.0,
        video_rotation_degrees=0,
        audio_stream_index=1,
        audio_codec="aac",
        audio_sample_rate_hz=48_000,
        audio_channels=2,
        mtime_ns=metadata.st_mtime_ns,
        inode=metadata.st_ino,
        device=metadata.st_dev,
    )


def test_review_model_rejects_partial_boundary_and_duplicate_partition() -> None:
    common = {
        "schema_version": "1",
        "plan_sha256": "a" * 64,
        "reviewer": "reviewer",
        "notes": (),
    }
    with pytest.raises(ValueError, match="supplied together"):
        OfflineSemanticReview.model_validate(
            common
            | {
                "selections": ({"clip_id": "clip_1", "start_cue_id": 1, "reason": "x"},),
                "rejected": (),
            }
        )
    with pytest.raises(ValueError, match="both selected and rejected"):
        OfflineSemanticReview.model_validate(
            common
            | {
                "selections": ({"clip_id": "clip_1", "reason": "x"},),
                "rejected": ({"clip_id": "clip_1", "reason": "y"},),
            }
        )


def test_reviewed_delivery_applies_cue_boundary_and_builds_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, transcript, plan, review, output = _write_inputs(tmp_path)
    monkeypatch.setattr(
        semantic_delivery,
        "ingest_source",
        lambda *_args, **_kwargs: _source_metadata(source),
    )
    render_calls = 0

    def fake_render(request: RenderRequest) -> RenderResult:
        nonlocal render_calls
        render_calls += 1
        output_path = request.output_path
        output_path.write_bytes(b"verified-video" * 200)
        sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
        return RenderResult(
            output_path=output_path,
            sha256=sha256,
            encoder="libx264",
            attempts=1,
            argv=("ffmpeg",),
            stderr_tail="",
            diagnostics=(),
        )

    monkeypatch.setattr(semantic_delivery, "render_clip", fake_render)
    result = render_reviewed_semantic_delivery(
        source_path=source.resolve(),
        transcript_path=transcript,
        plan_path=plan,
        review_path=review,
        output_dir=output,
        allowed_media_roots=(source.parent.resolve(),),
    )

    assert result.rendered_clip_count == 1
    assert result.new_render_count == 1
    assert result.reused_render_count == 0
    assert (result.delivery.directory / "index.html").is_file()
    manifest = json.loads(result.review_manifest_path.read_text(encoding="utf-8"))
    clip = manifest["clips"][0]
    assert clip["source_start_ms"] == 20_000
    assert clip["source_end_ms"] == 70_000
    assert clip["duration_ms"] == 50_000
    assert clip["boundary_changed"] is True
    assert clip["hook"] == "直接问题的答案是什么?"
    assert clip["reason"] == "片段包含直接问题、回答和结论。"
    assert clip["risk_flags"] == ["general_health_warning"]
    assert clip["keywords"]
    delivery_manifest = json.loads(result.delivery.manifest_path.read_text(encoding="utf-8"))
    assert delivery_manifest["clips"][0]["hook"] == "直接问题的答案是什么?"
    assert delivery_manifest["clips"][0]["keywords"]
    index = (result.delivery.directory / "index.html").read_text(encoding="utf-8")
    assert "高光语句" in index
    assert "直接问题的答案是什么?" in index
    assert "编辑关键词" in index
    assert manifest["rejected"] == [{"clip_id": "clip_02", "reason": "价值不足。"}]
    reused = render_reviewed_semantic_delivery(
        source_path=source.resolve(),
        transcript_path=transcript,
        plan_path=plan,
        review_path=review,
        output_dir=tmp_path / "reused-output",
        allowed_media_roots=(source.parent.resolve(),),
        reuse_render_manifest_path=result.review_manifest_path,
    )
    assert render_calls == 1
    assert reused.new_render_count == 0
    assert reused.reused_render_count == 1
    reused_manifest = json.loads(reused.review_manifest_path.read_text(encoding="utf-8"))
    assert reused_manifest["clips"][0]["reused_from"] == str(result.review_manifest_path)


def test_reviewed_delivery_requires_exact_plan_hash_and_full_classification(
    tmp_path: Path,
) -> None:
    source, transcript, plan, review, output = _write_inputs(tmp_path)
    payload = json.loads(review.read_text(encoding="utf-8"))
    payload["plan_sha256"] = "0" * 64
    review.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SemanticDeliveryError, match="exact semantic plan"):
        render_reviewed_semantic_delivery(
            source_path=source.resolve(),
            transcript_path=transcript,
            plan_path=plan,
            review_path=review,
            output_dir=output,
            allowed_media_roots=(source.parent.resolve(),),
        )


def test_offline_review_json_schema_is_current() -> None:
    schema_path = (
        Path(__file__).parents[2]
        / "src"
        / "liveclip"
        / "schemas"
        / "clipping"
        / "offline_review.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["properties"]["plan_sha256"]["pattern"] == "^[a-f0-9]{64}$"
    assert schema["properties"]["selections"]["minItems"] == 1
