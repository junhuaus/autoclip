"""Synthetic finished dual-profile run directories for Stage 19 tests.

Never depends on ``data/evaluations``: every run is built under ``tmp_path``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.edit_plan import captions_to_srt
from liveclip.pipeline.dual_profile import (
    CandidateDisposition,
    DualProfileFinalResult,
    DualProfileRunManifest,
    FinalProfileCandidate,
    FinalProfileResult,
    ProfileManifestStats,
    profile_statistics,
)
from liveclip.pipeline.srt import load_srt_transcript
from liveclip.services.captions import captions_for_clip

V9 = "quality-gate-risk-routing-v9"


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _candidate(
    *,
    candidate_id: str,
    profile: ClipProfile,
    start_ms: int,
    end_ms: int,
    cue_id: int,
    title: str,
    status: CandidateDisposition,
) -> FinalProfileCandidate:
    return FinalProfileCandidate(
        candidate_id=candidate_id,
        profile=profile,
        source_candidate_ids=(candidate_id,),
        source_window_ids=(f"{profile.value}_window",),
        start_cue_id=cue_id,
        end_cue_id=cue_id,
        start_ms=start_ms,
        end_ms=end_ms,
        duration_ms=end_ms - start_ms,
        title=title,
        hook=f"{title}高光语句",
        summary=f"{title}内容摘要",
        score=88,
        review_status=status,
        evidence_cue_ids=(cue_id,),
        review_reason=f"{title}内部审核理由",
    )


def _profile_result(
    candidate: FinalProfileCandidate, *extra: FinalProfileCandidate
) -> FinalProfileResult:
    values = (candidate, *extra)
    by_status: dict[str, list[FinalProfileCandidate]] = {}
    for value in values:
        by_status.setdefault(value.review_status.value, []).append(value)
    return FinalProfileResult(
        profile=candidate.profile,
        raw_candidate_ids=tuple(value.candidate_id for value in values),
        selected=tuple(by_status.get("selected", ())),
        manual_review=tuple(by_status.get("manual_review", ())),
        blocked=tuple(by_status.get("blocked", ())),
        statistics=profile_statistics(tuple(value.candidate_id for value in values), values),
    )


@dataclass
class RunFixture:
    base: Path
    root: Path
    run_dir: Path
    transcript: Path
    render_manifest: Path
    final: Path

    def manifest(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.render_manifest.read_text(encoding="utf-8"))
        return loaded

    def write_manifest(self, value: dict[str, Any]) -> None:
        self.render_manifest.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def build_run(
    base: Path,
    *,
    name: str = "run-1",
    routing: str | None = V9,
    relative_paths: bool = True,
    quality_status: str = "passed",
    include_blocked: bool = False,
    lesson_summary: str | None = None,
) -> RunFixture:
    root = base / "evaluations"
    run_dir = root / name
    run_dir.mkdir(parents=True)
    transcript = root / f"{name}-transcript.srt"
    transcript.write_text(
        "1\n00:00:00,000 --> 00:00:45,000\n短片完整教学主题\n\n"
        "2\n00:01:40,000 --> 00:03:20,001\n长片完整教学主题\n\n"
        "3\n00:04:00,000 --> 00:04:50,000\n被拦截的片段\n",
        encoding="utf-8",
    )
    source_hash = _sha(transcript.read_bytes())
    short = _candidate(
        candidate_id="short-one",
        profile=ClipProfile.SHORT_HIGHLIGHT,
        start_ms=0,
        end_ms=45_000,
        cue_id=1,
        title="短片教学",
        status=CandidateDisposition.SELECTED,
    )
    lesson = _candidate(
        candidate_id="lesson-one",
        profile=ClipProfile.MINI_LESSON,
        start_ms=100_000,
        end_ms=200_001,
        cue_id=2,
        title="小课教学",
        status=CandidateDisposition.MANUAL_REVIEW,
    )
    if lesson_summary is not None:
        lesson = lesson.model_copy(update={"summary": lesson_summary})
    blocked = _candidate(
        candidate_id="short-blocked",
        profile=ClipProfile.SHORT_HIGHLIGHT,
        start_ms=240_000,
        end_ms=290_000,
        cue_id=3,
        title="拦截片段",
        status=CandidateDisposition.BLOCKED,
    )
    short_extra = (blocked,) if include_blocked else ()
    final = DualProfileFinalResult(
        source_hash=source_hash,
        requested_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        executed_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        profiles={
            ClipProfile.SHORT_HIGHLIGHT: _profile_result(short, *short_extra),
            ClipProfile.MINI_LESSON: _profile_result(lesson),
        },
        routing_policy_version=routing,  # type: ignore[arg-type]
    )
    final_path = run_dir / "final-validated.json"
    final_path.write_text(
        json.dumps(final.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8"
    )
    run_manifest = DualProfileRunManifest(
        source_hash=source_hash,
        requested_profiles=final.requested_profiles,
        executed_profiles=final.executed_profiles,
        profiles={
            profile: ProfileManifestStats(**value.statistics.model_dump())
            for profile, value in final.profiles.items()
        },
        provider="mock",
        model="mock-model",
        prompt_files={"discovery": ("prompt.md",)},
        prompt_hashes={"short_highlight.discovery": "d" * 64},
        calls={"discovery": 2, "global_review": 2},
        input_tokens=100,
        output_tokens=20,
        latency_ms=50,
        cache_hits=0,
        retry_count=0,
        repair_count=0,
    )
    (run_dir / "run-manifest.json").write_text(
        json.dumps(run_manifest.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8"
    )
    transcript_doc = load_srt_transcript(transcript)
    render_root = run_dir / "renders"
    render_root.mkdir()

    def recorded(path: Path) -> str:
        return str(path.relative_to(base)) if relative_paths else str(path)

    clips: list[dict[str, object]] = []
    for candidate in (short, lesson):
        profile_dir = render_root / candidate.profile.value
        quality_dir = profile_dir / f"{candidate.candidate_id}-quality"
        quality_dir.mkdir(parents=True)
        video = profile_dir / f"{candidate.candidate_id}.mp4"
        video.write_bytes(f"video-{candidate.candidate_id}".encode())
        video_sha = _sha(video.read_bytes())
        captions = captions_for_clip(
            transcript_doc.segments,
            source_start_ms=candidate.start_ms,
            source_end_ms=candidate.end_ms,
        )
        subtitle = profile_dir / f"{candidate.candidate_id}.srt"
        subtitle.write_text(captions_to_srt(captions), encoding="utf-8")
        contact = quality_dir / "contact-sheet.png"
        contact.write_bytes(f"png-{candidate.candidate_id}".encode())
        quality = quality_dir / "quality-report.json"
        quality.write_text(
            json.dumps(
                {
                    "media_sha256": video_sha,
                    "automatic_status": quality_status,
                    "full_decode": "passed",
                }
            ),
            encoding="utf-8",
        )
        clips.append(
            {
                "candidate_id": candidate.candidate_id,
                "profile": candidate.profile.value,
                "variant_group_id": candidate.variant_group_id,
                "review_status": candidate.review_status.value,
                "start_ms": candidate.start_ms,
                "end_ms": candidate.end_ms,
                "duration_ms": candidate.duration_ms,
                "video_path": recorded(video),
                "video_sha256": video_sha,
                "subtitle_path": recorded(subtitle),
                "subtitle_sha256": _sha(subtitle.read_bytes()),
                "quality_report_path": str(quality),
                "contact_sheet_path": str(contact),
                "contact_sheet_sha256": _sha(contact.read_bytes()),
                "encoder": "fixture",
                "render_attempts": 1,
            }
        )
    render_manifest = render_root / "render-manifest.json"
    fixture = RunFixture(
        base=base,
        root=root,
        run_dir=run_dir,
        transcript=transcript,
        render_manifest=render_manifest,
        final=final_path,
    )
    fixture.write_manifest(
        {
            "schema_version": "1",
            "algorithm_version": "dual-profile-direct-v1",
            "source_video": "直播源.ts",
            "profiles": ["short_highlight", "mini_lesson"],
            "candidate_filter": ["lesson-one", "short-one"],
            "clip_count": 2,
            "clips": clips,
        }
    )
    return fixture
