#!/usr/bin/env python3
"""Run the frozen multi-video, three-model LiveClip highlight benchmark.

The generator processes are intentionally isolated from this development session:
they run ephemerally, ignore user config/rules, receive no tools, use a read-only
sandbox and see only the rendered runtime Agent instructions plus frozen evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_DIR = Path(__file__).resolve().parent
CASES_PATH = BENCHMARK_DIR / "cases.json"
SKILL_PATH = BENCHMARK_DIR / "agent-v1/SKILL.md"
GENERATION_SCHEMA_PATH = BENCHMARK_DIR / "schemas/highlight-output.schema.json"
JUDGE_PROMPT_PATH = BENCHMARK_DIR / "prompts/judge-v1.md"
JUDGE_SCHEMA_PATH = BENCHMARK_DIR / "schemas/judge-output.schema.json"
RESULTS_DIR = BENCHMARK_DIR / "results"
PILOT_DIR = ROOT / "docs/research/model-comparison-2026-08-17"

GENERATOR_CONFIGS = {
    "terra_medium": {"model": "gpt-5.6-terra", "effort": "medium"},
    "sol_medium": {"model": "gpt-5.6-sol", "effort": "medium"},
    "sol_high": {"model": "gpt-5.6-sol", "effort": "high"},
}
JUDGE_CONFIGS = {
    "terra_max": {"model": "gpt-5.6-terra", "effort": "max"},
    "sol_max": {"model": "gpt-5.6-sol", "effort": "max"},
}

DISABLED_FEATURES = (
    "apps",
    "artifact",
    "auth_elicitation",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "code_mode",
    "code_mode_buffered_exec",
    "code_mode_host",
    "code_mode_only",
    "computer_use",
    "default_mode_request_user_input",
    "deferred_executor",
    "deferred_tool_world_state",
    "enable_mcp_apps",
    "exec_permission_approvals",
    "executor_capability_discovery",
    "external_agent_memory_import",
    "goals",
    "guardian_approval",
    "hooks",
    "image_generation",
    "in_app_browser",
    "mcp_2026_07_28",
    "memories",
    "multi_agent",
    "network_proxy",
    "plugin_sharing",
    "plugins",
    "realtime_conversation",
    "remote_plugin",
    "request_permissions_tool",
    "shell_snapshot",
    "shell_tool",
    "skill_mcp_dependency_install",
    "skill_search",
    "standalone_web_search",
    "tool_call_mcp_elicitation",
    "tool_suggest",
    "unified_exec",
    "workspace_dependencies",
)
SAFE_ENV_KEYS = {
    "CODEX_HOME",
    "HOME",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "PATH",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TMPDIR",
    "USER",
}
ANONYMOUS_IDS = ("Q7", "M4", "R2")
PUNCTUATION_RE = re.compile(r"[^\w\u3400-\u9fff]+", re.UNICODE)
_FILE_SHA_CACHE: dict[Path, str] = {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cached_sha256(path: Path) -> str:
    resolved = path.resolve(strict=True)
    cached = _FILE_SHA_CACHE.get(resolved)
    if cached is None:
        cached = _sha256(resolved)
        _FILE_SHA_CACHE[resolved] = cached
    return cached


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _skill_body() -> str:
    value = SKILL_PATH.read_text(encoding="utf-8")
    if not value.startswith("---\n"):
        raise RuntimeError("runtime Agent SKILL.md has no YAML frontmatter")
    marker = value.find("\n---\n", 4)
    if marker < 0:
        raise RuntimeError("runtime Agent SKILL.md frontmatter is not closed")
    return value[marker + 5 :].lstrip("\n")


def _render_skill(source_label: str, duration_ms: int) -> str:
    return (
        _skill_body()
        .replace("{{SOURCE_LABEL}}", source_label)
        .replace("{{DURATION_MS}}", f"{duration_ms:,}")
    )


def _frozen_generation_schema(candidate_ids: list[str]) -> dict[str, Any]:
    schema = _json(GENERATION_SCHEMA_PATH)
    schema["properties"]["highlights"]["items"]["properties"]["candidate_id"] = {
        "type": "string",
        "enum": candidate_ids,
    }
    return schema


def _frozen_judge_schema(
    anonymous_ids: list[str],
    highlight_ids: list[str],
    candidate_ids: list[str],
) -> dict[str, Any]:
    schema = _json(JUDGE_SCHEMA_PATH)
    member = schema["properties"]["clusters"]["items"]["properties"]["members"][
        "items"
    ]["properties"]
    member["anonymous_system_id"] = {"type": "string", "enum": anonymous_ids}
    member["highlight_id"] = {"type": "string", "enum": highlight_ids}
    member["candidate_id"] = {"type": "string", "enum": candidate_ids}
    evaluation_id = schema["properties"]["system_evaluations"]["items"]["properties"]
    evaluation_id["anonymous_system_id"] = {
        "type": "string",
        "enum": anonymous_ids,
    }
    schema["properties"]["preferred_system_ids"]["items"] = {
        "type": "string",
        "enum": anonymous_ids,
    }
    return schema


def _ordered_candidates(
    candidates: list[dict[str, Any]], replicate_number: int, evidence_key: str
) -> list[dict[str, Any]]:
    ordered = list(candidates)
    if replicate_number == 1:
        return ordered
    if replicate_number == 2:
        return list(reversed(ordered))
    seed = int(
        hashlib.sha256(f"{evidence_key}:r{replicate_number:03d}".encode()).hexdigest()[:16],
        16,
    )
    random.Random(seed).shuffle(ordered)
    return ordered


def _load_evidence(
    evidence_key: str,
    config: dict[str, Any],
    replicate_number: int,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    source_path = ROOT / config["source_path"]
    transcript_path = ROOT / config["transcript_path"]
    rough_path = ROOT / config["rough_candidates_path"]
    for path in (source_path, transcript_path, rough_path):
        if not path.is_file():
            raise RuntimeError(f"required frozen evidence is missing: {path}")

    source_sha = _cached_sha256(source_path)
    if source_sha != config["expected_source_sha256"]:
        raise RuntimeError(f"source hash changed for {evidence_key}")
    for alias in config["source_aliases"]:
        alias_path = ROOT / "input" / alias
        if not alias_path.is_file():
            raise RuntimeError(f"source alias is missing for {evidence_key}: {alias}")
        if _cached_sha256(alias_path) != source_sha:
            raise RuntimeError(f"source alias is not byte-identical for {evidence_key}: {alias}")
    transcript = _json(transcript_path)
    rough = _json(rough_path)
    duration_ms = transcript.get("source_duration_ms")
    if not isinstance(duration_ms, int) or duration_ms <= 0:
        raise RuntimeError(f"invalid source duration for {evidence_key}")
    raw_candidates = rough.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise RuntimeError(f"no rough candidates for {evidence_key}")
    candidates = [
        {
            "candidate_id": item["candidate_id"],
            "source_start_ms": item["source_start_ms"],
            "source_end_ms": item["source_end_ms"],
            "allowed_start_ms": item["allowed_start_ms"],
            "allowed_end_ms": item["allowed_end_ms"],
            "text": item["text"],
            "context_before": item["context_before"],
            "context_after": item["context_after"],
            "rule_score": item["rule_score"],
            "rule_reasons": item["reasons"],
        }
        for item in raw_candidates
    ]
    candidates = _ordered_candidates(candidates, replicate_number, evidence_key)
    evidence = {
        "source": {
            "filename": config["source_label"],
            "duration_ms": duration_ms,
            "source_sha256": source_sha,
            "transcript_sha256": _cached_sha256(transcript_path),
            "rough_candidates_sha256": _cached_sha256(rough_path),
            "candidate_count": len(candidates),
            "evidence_note": (
                "Both systems receive this identical ASR-derived evidence; "
                "no video frames are supplied."
            ),
        },
        "candidates": candidates,
    }
    by_id = {item["candidate_id"]: item for item in candidates}
    if len(by_id) != len(candidates):
        raise RuntimeError(f"duplicate rough candidate ID for {evidence_key}")
    provenance = {
        "evidence_key": evidence_key,
        "benchmark_role": config["benchmark_role"],
        "source_aliases": config["source_aliases"],
        "project_id": config["project_id"],
        "run_id": config["run_id"],
        "generation": config["generation"],
        "transcript_segment_count": len(transcript.get("segments", [])),
        "candidate_order": (
            "original"
            if replicate_number == 1
            else "reverse"
            if replicate_number == 2
            else "seeded_shuffle"
        ),
    }
    return evidence, by_id, provenance


def _codex_command(*, model: str, effort: str, schema: Path, output: Path) -> list[str]:
    executable = shutil.which("codex")
    if executable is None:
        raise RuntimeError("codex CLI is unavailable")
    disabled = [value for name in DISABLED_FEATURES for value in ("--disable", name)]
    return [
        executable,
        "--ask-for-approval",
        "never",
        *disabled,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--strict-config",
        "--sandbox",
        "read-only",
        "-c",
        "features.shell_tool=false",
        "-c",
        "features.unified_exec=false",
        "-c",
        "features.multi_agent=false",
        "-c",
        'web_search="disabled"',
        "-c",
        f'model_reasoning_effort="{effort}"',
        "--model",
        model,
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(output),
        "--json",
        "--color",
        "never",
        "-",
    ]


def _parse_events(stdout: str) -> tuple[str | None, dict[str, int] | None, bool]:
    request_id: str | None = None
    usage: dict[str, int] | None = None
    unsafe_event = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            request_id = event["thread_id"]
        if isinstance(event.get("type"), str) and event["type"].startswith("item."):
            item = event.get("item")
            item_type = item.get("type") if isinstance(item, dict) else None
            if item_type not in {"agent_message", "reasoning"}:
                unsafe_event = True
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = {
                key: value
                for key, value in event["usage"].items()
                if isinstance(key, str)
                and re.fullmatch(r"[a-z_]{1,40}", key)
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            }
    return request_id, usage, unsafe_event


def _run_codex(
    *,
    label: str,
    model: str,
    effort: str,
    prompt: str,
    schema: Path,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    started_at = datetime.now(UTC)
    started = time.monotonic()
    print(f"START {label} {model}/{effort}", flush=True)
    with tempfile.TemporaryDirectory(prefix=f"liveclip-{label}-") as temp_value:
        output = Path(temp_value) / "result.json"
        completed = subprocess.run(
            _codex_command(model=model, effort=effort, schema=schema, output=output),
            input=prompt,
            text=True,
            capture_output=True,
            cwd=temp_value,
            env={key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV_KEYS},
            timeout=2_400,
            check=False,
        )
        request_id, usage, unsafe_event = _parse_events(completed.stdout)
        if completed.returncode != 0:
            tail = "\n".join(completed.stderr.splitlines()[-12:])
            raise RuntimeError(f"{label} failed with exit {completed.returncode}: {tail}")
        if unsafe_event:
            raise RuntimeError(f"{label} emitted a forbidden tool event")
        if not output.is_file():
            raise RuntimeError(f"{label} did not produce structured output")
        result = _json(output)
    metadata = {
        "label": label,
        "model": model,
        "reasoning_effort": effort,
        "request_id": request_id,
        "usage": usage,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "unsafe_tool_event": False,
    }
    print(f"DONE {label} {metadata['elapsed_seconds']}s", flush=True)
    return result, metadata, completed.stdout


def _normalize_evidence(value: str) -> str:
    return PUNCTUATION_RE.sub("", unicodedata.normalize("NFKC", value).casefold())


def _quote_alignment(quote: str, candidate_text: str) -> dict[str, Any]:
    normalized_quote = _normalize_evidence(quote)
    normalized_candidate = _normalize_evidence(candidate_text)
    exact = bool(normalized_quote) and normalized_quote in normalized_candidate
    matcher = SequenceMatcher(None, normalized_quote, normalized_candidate, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    coverage = matched / len(normalized_quote) if normalized_quote else 0.0
    status = "exact" if exact else "high_similarity" if coverage >= 0.85 else "failed"
    return {
        "status": status,
        "exact_normalized_substring": exact,
        "matched_character_coverage": round(coverage, 4),
    }


def _enrich_and_validate_generation(
    raw: dict[str, Any], candidates: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    highlights = raw.get("highlights")
    if not isinstance(highlights, list) or not 1 <= len(highlights) <= 12:
        raise RuntimeError("generation result has an invalid highlight count")
    enriched = json.loads(json.dumps(raw, ensure_ascii=False))
    seen: set[str] = set()
    alignments: list[dict[str, Any]] = []
    for position, highlight in enumerate(enriched["highlights"], start=1):
        candidate_id = highlight.get("candidate_id")
        if candidate_id not in candidates:
            raise RuntimeError(f"generation contains unknown candidate {candidate_id!r}")
        if candidate_id in seen:
            raise RuntimeError(f"generation repeats candidate {candidate_id!r}")
        seen.add(candidate_id)
        candidate = candidates[candidate_id]
        highlight["source_start_ms"] = candidate["source_start_ms"]
        highlight["source_end_ms"] = candidate["source_end_ms"]
        alignment = _quote_alignment(highlight["highlight_sentence"], candidate["text"])
        alignments.append(
            {
                "position": position,
                "candidate_id": candidate_id,
                "highlight_sentence": highlight["highlight_sentence"],
                **alignment,
            }
        )
    exact_count = sum(item["status"] == "exact" for item in alignments)
    failed_count = sum(item["status"] == "failed" for item in alignments)
    validation = {
        "schema_and_candidate_gate": "passed",
        "selected_count": len(highlights),
        "unique_candidate_count": len(seen),
        "quote_alignment": alignments,
        "exact_quote_count": exact_count,
        "failed_quote_count": failed_count,
        "exact_quote_rate": round(exact_count / len(highlights), 4),
        "note": (
            "Skill v1 has one edited highlight_sentence field, so exact matching is measured "
            "but not used to silently repair or discard output."
        ),
    }
    return enriched, validation


def _existing_output(output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]] | None:
    result_path = output_dir / "result.json"
    metadata_path = output_dir / "call-metadata.json"
    validation_path = output_dir / "validation.json"
    if not (result_path.is_file() and metadata_path.is_file() and validation_path.is_file()):
        return None
    result = _json(result_path)
    metadata = _json(metadata_path)
    if metadata.get("result_sha256") != _sha256(result_path):
        raise RuntimeError(f"existing output hash mismatch: {result_path}")
    return result, _json(validation_path)


def _reuse_pilot(
    config_name: str,
    output_dir: Path,
    evidence: dict[str, Any],
    generation_schema: dict[str, Any],
    rendered_skill: str,
    candidates: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    pilot_names = {
        "terra_medium": "terra-medium",
        "sol_medium": "sol-medium",
    }
    pilot_name = pilot_names.get(config_name)
    if pilot_name is None:
        return None
    if evidence != _json(PILOT_DIR / "frozen-input.json"):
        raise RuntimeError("pilot reuse rejected: frozen evidence differs")
    if generation_schema != _json(PILOT_DIR / "highlight-script.frozen.schema.json"):
        raise RuntimeError("pilot reuse rejected: frozen generation Schema differs")
    if rendered_skill != (PILOT_DIR / "generation-prompt.md").read_text(encoding="utf-8"):
        raise RuntimeError("pilot reuse rejected: rendered runtime Agent instructions differ")
    raw = _json(PILOT_DIR / f"{pilot_name}.raw.json")
    enriched, validation = _enrich_and_validate_generation(raw, candidates)
    if enriched != _json(PILOT_DIR / f"{pilot_name}.json"):
        raise RuntimeError("pilot reuse rejected: enriched output differs")
    pilot_metadata = _json(PILOT_DIR / "run-metadata.json")
    call = next(item for item in pilot_metadata["calls"] if item["label"] == pilot_name)
    _write_json(output_dir / "result.raw.json", raw)
    _write_json(output_dir / "result.json", enriched)
    _write_json(output_dir / "validation.json", validation)
    metadata = {
        **call,
        "reused": True,
        "reused_from": str((PILOT_DIR / f"{pilot_name}.json").relative_to(ROOT)),
        "result_sha256": _sha256(output_dir / "result.json"),
    }
    _write_json(output_dir / "call-metadata.json", metadata)
    print(f"REUSE pilot {config_name}", flush=True)
    return enriched, validation


def _run_generator(
    *,
    case_id: str,
    replicate_id: str,
    config_name: str,
    config: dict[str, str],
    output_dir: Path,
    prompt: str,
    schema_path: Path,
    candidates: dict[str, dict[str, Any]],
    force: bool,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if not force:
        existing = _existing_output(output_dir)
        if existing is not None:
            print(f"RESUME {case_id}/{replicate_id}/{config_name}", flush=True)
            return config_name, existing[0], existing[1]
    raw, metadata, events = _run_codex(
        label=f"{case_id}-{replicate_id}-{config_name}",
        model=config["model"],
        effort=config["effort"],
        prompt=prompt,
        schema=schema_path,
    )
    enriched, validation = _enrich_and_validate_generation(raw, candidates)
    _write_json(output_dir / "result.raw.json", raw)
    _write_json(output_dir / "result.json", enriched)
    _write_json(output_dir / "validation.json", validation)
    _write_text(output_dir / "events.jsonl", events)
    metadata["reused"] = False
    metadata["result_sha256"] = _sha256(output_dir / "result.json")
    _write_json(output_dir / "call-metadata.json", metadata)
    return config_name, enriched, validation


def _judge_input(
    *,
    evidence: dict[str, Any],
    generator_results: dict[str, dict[str, Any]],
    judge_name: str,
    case_id: str,
    replicate_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    seed_text = f"{case_id}:{replicate_id}:{judge_name}:anonymous-v1"
    rng = random.Random(int(hashlib.sha256(seed_text.encode()).hexdigest()[:16], 16))
    model_names = list(GENERATOR_CONFIGS)
    rng.shuffle(model_names)
    anonymous_ids = list(ANONYMOUS_IDS)
    rng.shuffle(anonymous_ids)
    system_mapping = dict(zip(anonymous_ids, model_names, strict=True))
    candidates = {item["candidate_id"]: item for item in evidence["candidates"]}
    selected_ids: set[str] = set()
    systems: list[dict[str, Any]] = []
    highlight_mapping: dict[str, dict[str, str]] = {}
    all_highlight_ids: list[str] = []
    for anonymous_id, model_name in system_mapping.items():
        highlights = []
        mapping_for_system: dict[str, str] = {}
        for index, item in enumerate(generator_results[model_name]["highlights"], start=1):
            highlight_id = f"h{index:02d}"
            mapping_for_system[highlight_id] = item["candidate_id"]
            all_highlight_ids.append(highlight_id)
            selected_ids.add(item["candidate_id"])
            highlights.append(
                {
                    "highlight_id": highlight_id,
                    "candidate_id": item["candidate_id"],
                    "topic": item["topic"],
                    "title": item["title"],
                    "highlight_sentence": item["highlight_sentence"],
                    "script_description": item["script_description"],
                    "hook": item["hook"],
                    "selection_reason": item["selection_reason"],
                    "risk_flags": item["risk_flags"],
                }
            )
        rng.shuffle(highlights)
        highlight_mapping[anonymous_id] = mapping_for_system
        systems.append({"anonymous_system_id": anonymous_id, "highlights": highlights})
    rng.shuffle(systems)
    evidence_items = []
    for candidate_id in sorted(selected_ids):
        item = candidates[candidate_id]
        evidence_items.append(
            {
                "candidate_id": candidate_id,
                "source_start_ms": item["source_start_ms"],
                "source_end_ms": item["source_end_ms"],
                "text": item["text"],
                "context_before": item["context_before"],
                "context_after": item["context_after"],
            }
        )
    judge_input = {
        "source": {
            "duration_ms": evidence["source"]["duration_ms"],
            "source_sha256": evidence["source"]["source_sha256"],
            "evidence_note": "Text-only frozen evidence; no video frames are available.",
        },
        "selected_candidate_evidence": evidence_items,
        "anonymous_systems": systems,
    }
    mapping = {
        "seed_sha256": hashlib.sha256(seed_text.encode()).hexdigest(),
        "anonymous_system_mapping": system_mapping,
        "highlight_candidate_mapping": highlight_mapping,
        "all_highlight_keys": sorted(
            f"{system_id}:{highlight_id}"
            for system_id, values in highlight_mapping.items()
            for highlight_id in values
        ),
    }
    return judge_input, mapping


def _score_system(evaluation: dict[str, Any]) -> float:
    weights = {
        "topic_discovery": 30,
        "evidence_fidelity": 20,
        "clip_selection": 20,
        "editorial_usability": 15,
        "portfolio_quality": 15,
    }
    return round(sum(evaluation[key] / 4 * weight for key, weight in weights.items()), 1)


def _validate_judge(
    result: dict[str, Any], mapping: dict[str, Any]
) -> dict[str, Any]:
    system_mapping = mapping["anonymous_system_mapping"]
    expected_systems = set(system_mapping)
    evaluations = result.get("system_evaluations")
    if not isinstance(evaluations, list):
        raise RuntimeError("judge has no system evaluations")
    evaluation_ids = [item.get("anonymous_system_id") for item in evaluations]
    if set(evaluation_ids) != expected_systems or len(evaluation_ids) != len(set(evaluation_ids)):
        raise RuntimeError("judge system evaluations do not cover each anonymous system once")
    preferred = result.get("preferred_system_ids")
    if not isinstance(preferred, list) or not preferred:
        raise RuntimeError("judge preferred_system_ids is empty")
    if not set(preferred) <= expected_systems or len(preferred) != len(set(preferred)):
        raise RuntimeError("judge preferred_system_ids is invalid")

    expected_highlights = set(mapping["all_highlight_keys"])
    observed_highlights: list[str] = []
    cluster_ids: set[str] = set()
    clusters_per_system = {system_id: set() for system_id in expected_systems}
    member_counts_per_system = {system_id: 0 for system_id in expected_systems}
    for cluster in result.get("clusters", []):
        cluster_id = cluster.get("cluster_id")
        if cluster_id in cluster_ids:
            raise RuntimeError(f"judge repeats cluster ID {cluster_id!r}")
        cluster_ids.add(cluster_id)
        for member in cluster.get("members", []):
            system_id = member.get("anonymous_system_id")
            highlight_id = member.get("highlight_id")
            if system_id not in expected_systems:
                raise RuntimeError("judge member uses unknown system")
            expected_candidate = mapping["highlight_candidate_mapping"][system_id].get(
                highlight_id
            )
            if expected_candidate != member.get("candidate_id"):
                raise RuntimeError("judge member candidate does not match blinded highlight")
            key = f"{system_id}:{highlight_id}"
            observed_highlights.append(key)
            clusters_per_system[system_id].add(cluster_id)
            member_counts_per_system[system_id] += 1
    if set(observed_highlights) != expected_highlights or len(observed_highlights) != len(
        expected_highlights
    ):
        raise RuntimeError("judge clusters do not cover every highlight exactly once")

    totals_by_model: dict[str, float] = {}
    atomics_by_model: dict[str, dict[str, int]] = {}
    for evaluation in evaluations:
        system_id = evaluation["anonymous_system_id"]
        model_name = system_mapping[system_id]
        totals_by_model[model_name] = _score_system(evaluation)
        atomics_by_model[model_name] = {
            key: evaluation[key]
            for key in (
                "topic_discovery",
                "evidence_fidelity",
                "clip_selection",
                "editorial_usability",
                "portfolio_quality",
            )
        }

    pairwise_semantic_jaccard: dict[str, float] = {}
    model_to_system = {model: system for system, model in system_mapping.items()}
    model_names = sorted(model_to_system)
    for index, model_a in enumerate(model_names):
        for model_b in model_names[index + 1 :]:
            topics_a = clusters_per_system[model_to_system[model_a]]
            topics_b = clusters_per_system[model_to_system[model_b]]
            union = topics_a | topics_b
            value = len(topics_a & topics_b) / len(union) if union else 1.0
            pairwise_semantic_jaccard[f"{model_a}__{model_b}"] = round(value, 4)

    duplicate_rate_by_model: dict[str, float] = {}
    topic_count_by_model: dict[str, int] = {}
    for model_name, system_id in model_to_system.items():
        selected = member_counts_per_system[system_id]
        unique_topics = len(clusters_per_system[system_id])
        topic_count_by_model[model_name] = unique_topics
        duplicate_rate_by_model[model_name] = round(
            (selected - unique_topics) / selected if selected else 0.0,
            4,
        )
    preferred_models = [system_mapping[system_id] for system_id in preferred]
    return {
        "cluster_coverage_gate": "passed",
        "cluster_count": len(cluster_ids),
        "computed_total_by_model": totals_by_model,
        "atomic_scores_by_model": atomics_by_model,
        "preferred_models": preferred_models,
        "topic_count_by_model": topic_count_by_model,
        "semantic_duplicate_rate_by_model": duplicate_rate_by_model,
        "pairwise_semantic_jaccard": pairwise_semantic_jaccard,
    }


def _run_judge(
    *,
    case_id: str,
    replicate_id: str,
    judge_name: str,
    config: dict[str, str],
    output_dir: Path,
    judge_input: dict[str, Any],
    mapping: dict[str, Any],
    schema_path: Path,
    force: bool,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if not force:
        existing = _existing_output(output_dir)
        if existing is not None:
            print(f"RESUME {case_id}/{replicate_id}/{judge_name}", flush=True)
            return judge_name, existing[0], existing[1]
    prompt = (
        JUDGE_PROMPT_PATH.read_text(encoding="utf-8")
        + "\n\n<untrusted_blind_evaluation_input>\n"
        + _canonical_bytes(judge_input).decode("utf-8")
        + "\n</untrusted_blind_evaluation_input>\n"
    )
    result, metadata, events = _run_codex(
        label=f"{case_id}-{replicate_id}-{judge_name}",
        model=config["model"],
        effort=config["effort"],
        prompt=prompt,
        schema=schema_path,
    )
    validation = _validate_judge(result, mapping)
    _write_json(output_dir / "input.json", judge_input)
    _write_json(output_dir / "result.json", result)
    _write_json(output_dir / "validation.json", validation)
    _write_text(output_dir / "events.jsonl", events)
    metadata["result_sha256"] = _sha256(output_dir / "result.json")
    _write_json(output_dir / "call-metadata.json", metadata)
    # The model never sees this mapping. It is persisted only after judging succeeds.
    _write_json(output_dir / "mapping.disclosed-after-judging.json", mapping)
    return judge_name, result, validation


def _prepare_replicate(
    case: dict[str, Any],
    evidence_config: dict[str, Any],
    replicate_number: int,
) -> tuple[
    Path,
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, Any],
    str,
    Path,
]:
    case_id = case["case_id"]
    replicate_id = f"r{replicate_number:03d}"
    replicate_dir = RESULTS_DIR / case_id / replicate_id
    evidence, candidates, provenance = _load_evidence(
        case["evidence_set"], evidence_config, replicate_number
    )
    rendered_skill = _render_skill(
        evidence_config["source_label"], evidence["source"]["duration_ms"]
    )
    schema = _frozen_generation_schema([item["candidate_id"] for item in evidence["candidates"]])
    schema_path = replicate_dir / "frozen-generation-schema.json"
    _write_json(replicate_dir / "frozen-input.json", evidence)
    _write_json(schema_path, schema)
    _write_text(replicate_dir / "runtime-agent-instructions.md", rendered_skill)
    _write_json(
        replicate_dir / "provenance.json",
        {
            **provenance,
            "case_id": case_id,
            "replicate_id": replicate_id,
            "include_in_primary_aggregate": case["include_in_primary_aggregate"],
            "source_sha256": evidence["source"]["source_sha256"],
            "transcript_sha256": evidence["source"]["transcript_sha256"],
            "rough_candidates_sha256": evidence["source"]["rough_candidates_sha256"],
            "runtime_agent_sha256": _sha256_bytes(rendered_skill.encode()),
            "generation_schema_sha256": _sha256(schema_path),
            "candidate_order_sha256": _sha256_bytes(
                _canonical_bytes([item["candidate_id"] for item in evidence["candidates"]])
            ),
        },
    )
    generation_prompt = (
        rendered_skill
        + "\n\n<untrusted_frozen_input>\n"
        + _canonical_bytes(evidence).decode("utf-8")
        + "\n</untrusted_frozen_input>\n"
    )
    return (
        replicate_dir,
        evidence,
        candidates,
        provenance,
        generation_prompt,
        schema_path,
    )


def _run_replicate(
    *,
    case: dict[str, Any],
    evidence_config: dict[str, Any],
    replicate_number: int,
    stage: str,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    case_id = case["case_id"]
    replicate_id = f"r{replicate_number:03d}"
    (
        replicate_dir,
        evidence,
        candidates,
        provenance,
        generation_prompt,
        generation_schema_path,
    ) = _prepare_replicate(case, evidence_config, replicate_number)
    if dry_run:
        print(f"DRY-RUN {case_id}/{replicate_id} evidence frozen", flush=True)
        return {"case_id": case_id, "replicate_id": replicate_id, "dry_run": True}

    generator_results: dict[str, dict[str, Any]] = {}
    generator_validations: dict[str, dict[str, Any]] = {}
    if stage in {"all", "generation"}:
        if evidence_config.get("reuse_from") and replicate_number == 1 and not force:
            for config_name in ("terra_medium", "sol_medium"):
                reused = _reuse_pilot(
                    config_name,
                    replicate_dir / "generators" / config_name,
                    evidence,
                    _json(generation_schema_path),
                    (replicate_dir / "runtime-agent-instructions.md").read_text(
                        encoding="utf-8"
                    ),
                    candidates,
                )
                if reused is not None:
                    generator_results[config_name], generator_validations[config_name] = reused
        pending = [name for name in GENERATOR_CONFIGS if name not in generator_results]
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(
                    _run_generator,
                    case_id=case_id,
                    replicate_id=replicate_id,
                    config_name=config_name,
                    config=GENERATOR_CONFIGS[config_name],
                    output_dir=replicate_dir / "generators" / config_name,
                    prompt=generation_prompt,
                    schema_path=generation_schema_path,
                    candidates=candidates,
                    force=force,
                ): config_name
                for config_name in pending
            }
            for future in as_completed(futures):
                config_name = futures[future]
                try:
                    name, result, validation = future.result()
                    generator_results[name] = result
                    generator_validations[name] = validation
                except Exception as exc:  # preserve other completed calls before failing
                    errors.append(f"{config_name}: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))
    else:
        for config_name in GENERATOR_CONFIGS:
            existing = _existing_output(replicate_dir / "generators" / config_name)
            if existing is None:
                raise RuntimeError(
                    f"missing generator output for {case_id}/{replicate_id}/{config_name}"
                )
            generator_results[config_name], generator_validations[config_name] = existing

    judge_results: dict[str, dict[str, Any]] = {}
    judge_validations: dict[str, dict[str, Any]] = {}
    if stage in {"all", "judge"}:
        judge_jobs: dict[str, tuple[dict[str, Any], dict[str, Any], Path]] = {}
        for judge_name in JUDGE_CONFIGS:
            judge_input, mapping = _judge_input(
                evidence=evidence,
                generator_results=generator_results,
                judge_name=judge_name,
                case_id=case_id,
                replicate_id=replicate_id,
            )
            ids = list(mapping["anonymous_system_mapping"])
            all_highlight_ids = sorted(
                {
                    highlight_id
                    for values in mapping["highlight_candidate_mapping"].values()
                    for highlight_id in values
                }
            )
            selected_candidate_ids = sorted(
                {
                    candidate_id
                    for values in mapping["highlight_candidate_mapping"].values()
                    for candidate_id in values.values()
                }
            )
            judge_schema = _frozen_judge_schema(ids, all_highlight_ids, selected_candidate_ids)
            judge_schema_path = replicate_dir / "judges" / judge_name / "frozen-schema.json"
            _write_json(judge_schema_path, judge_schema)
            judge_jobs[judge_name] = (judge_input, mapping, judge_schema_path)
        errors = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(
                    _run_judge,
                    case_id=case_id,
                    replicate_id=replicate_id,
                    judge_name=judge_name,
                    config=JUDGE_CONFIGS[judge_name],
                    output_dir=replicate_dir / "judges" / judge_name,
                    judge_input=values[0],
                    mapping=values[1],
                    schema_path=values[2],
                    force=force,
                ): judge_name
                for judge_name, values in judge_jobs.items()
            }
            for future in as_completed(futures):
                judge_name = futures[future]
                try:
                    name, result, validation = future.result()
                    judge_results[name] = result
                    judge_validations[name] = validation
                except Exception as exc:
                    errors.append(f"{judge_name}: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))

    summary = {
        "case_id": case_id,
        "replicate_id": replicate_id,
        "benchmark_role": provenance["benchmark_role"],
        "include_in_primary_aggregate": case["include_in_primary_aggregate"],
        "generator_validation": generator_validations,
        "judge_validation": judge_validations,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    _write_json(replicate_dir / "replicate-summary.json", summary)
    return summary


def _protocol(cases_config: dict[str, Any]) -> dict[str, Any]:
    executable = shutil.which("codex")
    version = None
    if executable:
        completed = subprocess.run(
            [executable, "--version"], text=True, capture_output=True, check=False, timeout=15
        )
        version = completed.stdout.strip() or completed.stderr.strip()
    return {
        "schema_version": "1",
        "benchmark_name": "LiveClip three-model free-discovery benchmark",
        "created_at": datetime.now(UTC).isoformat(),
        "unique_source_count": 3,
        "primary_case_count": 3,
        "diagnostic_case_count": 1,
        "generator_models": GENERATOR_CONFIGS,
        "judge_models": JUDGE_CONFIGS,
        "generator_replicates_per_primary_case": 3,
        "candidate_order_variants": ["original", "reverse", "seeded_shuffle"],
        "aggregation_rule": (
            "Macro-average three unique source SHA-256 values. The ASR evidence sensitivity "
            "case and filename aliases have zero primary statistical weight."
        ),
        "runtime_isolation": {
            "ephemeral": True,
            "ignore_user_config": True,
            "ignore_rules": True,
            "sandbox": "read-only",
            "tools": "disabled",
            "environment": "allowlist",
        },
        "codex_cli": {"path": executable, "version": version},
        "artifact_sha256": {
            "cases": _sha256(CASES_PATH),
            "runtime_agent_skill": _sha256(SKILL_PATH),
            "generation_schema": _sha256(GENERATION_SCHEMA_PATH),
            "judge_prompt": _sha256(JUDGE_PROMPT_PATH),
            "judge_schema": _sha256(JUDGE_SCHEMA_PATH),
        },
        "cases": cases_config["cases"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--replicate", type=int, action="append", dest="replicates")
    parser.add_argument("--stage", choices=("all", "generation", "judge"), default="all")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cases_config = _json(CASES_PATH)
    protocol_path = BENCHMARK_DIR / "protocol.json"
    if protocol_path.exists() and not args.force:
        prior_protocol = _json(protocol_path)
        prior_hashes = prior_protocol.get("artifact_sha256")
        current_hashes = _protocol(cases_config)["artifact_sha256"]
        if prior_hashes != current_hashes:
            raise RuntimeError("protocol inputs changed; use a new benchmark directory")
    else:
        _write_json(protocol_path, _protocol(cases_config))

    selected_cases = [
        case
        for case in cases_config["cases"]
        if not args.case_ids or case["case_id"] in set(args.case_ids)
    ]
    if args.case_ids and {case["case_id"] for case in selected_cases} != set(args.case_ids):
        raise RuntimeError("one or more requested case IDs are unknown")

    summaries = []
    for case in selected_cases:
        evidence_config = cases_config["evidence_sets"][case["evidence_set"]]
        replicate_numbers = list(range(1, case["replicates"] + 1))
        if args.replicates:
            replicate_numbers = [
                number for number in replicate_numbers if number in set(args.replicates)
            ]
        for replicate_number in replicate_numbers:
            summaries.append(
                _run_replicate(
                    case=case,
                    evidence_config=evidence_config,
                    replicate_number=replicate_number,
                    stage=args.stage,
                    force=args.force,
                    dry_run=args.dry_run,
                )
            )

    run_summary = {
        "schema_version": "1",
        "updated_at": datetime.now(UTC).isoformat(),
        "stage": args.stage,
        "dry_run": args.dry_run,
        "completed_replicates": summaries,
    }
    _write_json(BENCHMARK_DIR / "run-summary.json", run_summary)
    print(json.dumps(run_summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
