#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from liveclip.pipeline.dual_profile import DualProfileFinalResult, FinalProfileCandidate
from liveclip.pipeline.semantic_global import transcript_cues
from liveclip.pipeline.srt import load_srt_transcript


def _timestamp(milliseconds: int) -> str:
    seconds, millis = divmod(milliseconds, 1_000)
    minutes, second = divmod(seconds, 60)
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}.{millis:03d}"


def _matched_candidate_ids(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("benchmark result must be one JSON object")
    matches = (*payload.get("short_matches", ()), *payload.get("mini_lesson_matches", ()))
    return {
        str(value["candidate_id"])
        for value in matches
        if isinstance(value, dict) and "candidate_id" in value
    }


def export_scripts(
    *,
    final_path: Path,
    transcript_path: Path,
    output_dir: Path,
    benchmark_result_path: Path | None = None,
) -> tuple[Path, Path]:
    final = DualProfileFinalResult.model_validate_json(final_path.read_text(encoding="utf-8"))
    transcript = load_srt_transcript(transcript_path)
    cue_map = {value.cue_id: value for value in transcript_cues(transcript)}
    requested_ids = _matched_candidate_ids(benchmark_result_path)
    candidates = tuple(
        value
        for profile in final.executed_profiles
        for values in (final.profiles[profile].selected, final.profiles[profile].manual_review)
        for value in values
        if requested_ids is None or value.candidate_id in requested_ids
    )
    if requested_ids is not None:
        missing = requested_ids - {value.candidate_id for value in candidates}
        if missing:
            raise ValueError(
                "benchmark matches missing from final result: " + ", ".join(sorted(missing))
            )
    output_dir.mkdir(parents=True, exist_ok=True)
    payload: list[dict[str, Any]] = []
    markdown = ["# LiveClip 双轨切分脚本", ""]
    for candidate in candidates:
        cues = [
            cue_map[cue_id].model_dump(mode="json")
            for cue_id in range(candidate.start_cue_id, candidate.end_cue_id + 1)
        ]
        payload.append(
            {
                "candidate": candidate.model_dump(mode="json"),
                "transcript_cues": cues,
            }
        )
        markdown.extend(_candidate_markdown(candidate, cues))
    json_path = output_dir / "cut-scripts.json"
    markdown_path = output_dir / "cut-scripts.md"
    json_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "source_hash": final.source_hash,
                "candidate_count": len(payload),
                "scripts": payload,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text("\n".join(markdown).rstrip() + "\n", encoding="utf-8")
    return json_path, markdown_path


def _candidate_markdown(candidate: FinalProfileCandidate, cues: list[dict[str, Any]]) -> list[str]:
    lines = [
        f"## {candidate.candidate_id} — {candidate.title}",
        "",
        f"- Profile: `{candidate.profile.value}`",
        f"- Variant group: `{candidate.variant_group_id}`",
        f"- Status: `{candidate.review_status.value}`; score: `{candidate.score:g}`",
        f"- Range: `{_timestamp(candidate.start_ms)}-{_timestamp(candidate.end_ms)}` "
        f"({candidate.duration_ms / 1_000:.3f}s; "
        f"cues {candidate.start_cue_id}-{candidate.end_cue_id})",
        "- Quality flags: `"
        + (", ".join(value.value for value in candidate.quality_flags) or "none")
        + "`",
        f"- Risk tags: `{', '.join(value.value for value in candidate.risk_tags) or 'none'}`",
        "",
        candidate.summary,
        "",
        "### 原始连续字幕",
        "",
    ]
    lines.extend(
        f"[{cue['cue_id']} | {_timestamp(int(cue['start_ms']))}-"
        f"{_timestamp(int(cue['end_ms']))}] {cue['original_text']}"
        for cue in cues
    )
    lines.append("")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Export auditable dual-profile cut scripts")
    parser.add_argument("final_validated", type=Path)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--benchmark-result", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    json_path, markdown_path = export_scripts(
        final_path=args.final_validated,
        transcript_path=args.transcript,
        output_dir=args.output_dir,
        benchmark_result_path=args.benchmark_result,
    )
    print(json.dumps({"json": str(json_path), "markdown": str(markdown_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
