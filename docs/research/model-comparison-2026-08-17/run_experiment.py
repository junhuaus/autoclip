#!/usr/bin/env python3
"""Run the frozen 8-16-1 LiveClip model comparison and blind judge."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT_DIR = Path(__file__).resolve().parent
ROUGH_CANDIDATES = (
    ROOT
    / "data/projects/953ae56cf15f486cb61ab5b53046ebb5/runs/g001/candidates/rough-candidates.json"
)
TRANSCRIPT = (
    ROOT
    / "data/projects/953ae56cf15f486cb61ab5b53046ebb5/runs/g001/transcript/transcript.json"
)
SOURCE = ROOT / "input/8-16-1.ts"
GENERATION_PROMPT = EXPERIMENT_DIR / "generation-prompt.md"
GENERATION_SCHEMA = EXPERIMENT_DIR / "highlight-script.schema.json"
JUDGE_PROMPT = EXPERIMENT_DIR / "judge-prompt.md"
JUDGE_SCHEMA = EXPERIMENT_DIR / "judge.schema.json"
COMMON_TOPICS = EXPERIMENT_DIR / "common-topics.json"
PAIRED_GENERATION_PROMPT = EXPERIMENT_DIR / "paired-generation-prompt.md"
PAIRED_GENERATION_SCHEMA = EXPERIMENT_DIR / "paired-highlight-script.schema.json"
PAIRED_JUDGE_PROMPT = EXPERIMENT_DIR / "paired-judge-prompt.md"
PAIRED_JUDGE_SCHEMA = EXPERIMENT_DIR / "paired-judge.schema.json"

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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


def _load_evidence() -> dict[str, Any]:
    rough = json.loads(ROUGH_CANDIDATES.read_text(encoding="utf-8"))
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
        for item in rough["candidates"]
    ]
    return {
        "source": {
            "filename": SOURCE.name,
            "duration_ms": 5_042_717,
            "source_sha256": _sha256(SOURCE),
            "transcript_sha256": _sha256(TRANSCRIPT),
            "rough_candidates_sha256": _sha256(ROUGH_CANDIDATES),
            "candidate_count": len(candidates),
            "evidence_note": (
                "Both systems receive this identical ASR-derived evidence; "
                "no video frames are supplied."
            ),
        },
        "candidates": candidates,
    }


def _frozen_generation_schema(evidence: dict[str, Any]) -> Path:
    schema = json.loads(GENERATION_SCHEMA.read_text(encoding="utf-8"))
    candidate_ids = [item["candidate_id"] for item in evidence["candidates"]]
    schema["properties"]["highlights"]["items"]["properties"]["candidate_id"] = {
        "type": "string",
        "enum": candidate_ids,
    }
    path = EXPERIMENT_DIR / "highlight-script.frozen.schema.json"
    _write_json(path, schema)
    return path


def _frozen_paired_generation_schema(evidence: dict[str, Any]) -> Path:
    schema = json.loads(PAIRED_GENERATION_SCHEMA.read_text(encoding="utf-8"))
    candidate_ids = [item["candidate_id"] for item in evidence["candidates"]]
    schema["$defs"]["topicScript"]["properties"]["candidate_id"] = {
        "type": "string",
        "enum": candidate_ids,
    }
    path = EXPERIMENT_DIR / "paired-highlight-script.frozen.schema.json"
    _write_json(path, schema)
    return path


def _frozen_paired_judge_schema(
    common_topics: dict[str, Any],
    system_a: dict[str, Any],
    system_b: dict[str, Any],
) -> Path:
    schema = json.loads(PAIRED_JUDGE_SCHEMA.read_text(encoding="utf-8"))
    comparison_template = schema["$defs"]["topicComparison"]
    properties = schema["properties"]["per_topic"]["properties"]
    for topic in common_topics["topics"]:
        topic_id = topic["topic_id"]
        comparison = json.loads(json.dumps(comparison_template))
        comparison["properties"]["label"] = {
            "type": "string",
            "enum": [topic["label"]],
        }
        comparison["properties"]["system_a_candidate_id"] = {
            "type": "string",
            "enum": [system_a["topics"][topic_id]["candidate_id"]],
        }
        comparison["properties"]["system_b_candidate_id"] = {
            "type": "string",
            "enum": [system_b["topics"][topic_id]["candidate_id"]],
        }
        properties[topic_id] = comparison
    path = EXPERIMENT_DIR / "paired-judge.frozen.schema.json"
    _write_json(path, schema)
    return path


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


def _metadata(stdout: str) -> tuple[str | None, dict[str, int] | None, bool]:
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
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"liveclip-{label}-") as temp_value:
        output = Path(temp_value) / "result.json"
        completed = subprocess.run(
            _codex_command(model=model, effort=effort, schema=schema, output=output),
            input=prompt,
            text=True,
            capture_output=True,
            cwd=temp_value,
            env={key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV_KEYS},
            timeout=1_800,
            check=False,
        )
        request_id, usage, unsafe_event = _metadata(completed.stdout)
        if completed.returncode != 0:
            tail = "\n".join(completed.stderr.splitlines()[-8:])
            raise RuntimeError(f"{label} failed with exit {completed.returncode}: {tail}")
        if unsafe_event:
            raise RuntimeError(f"{label} emitted a forbidden tool event")
        if not output.is_file():
            raise RuntimeError(f"{label} did not produce structured output")
        result = json.loads(output.read_text(encoding="utf-8"))
    metadata = {
        "label": label,
        "model": model,
        "reasoning_effort": effort,
        "request_id": request_id,
        "usage": usage,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    return result, metadata


def _enrich_generation(result: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    candidates = {item["candidate_id"]: item for item in evidence["candidates"]}
    highlights = result.get("highlights")
    if not isinstance(highlights, list) or not 1 <= len(highlights) <= 12:
        raise RuntimeError("generation result has an invalid highlight count")
    enriched = json.loads(json.dumps(result, ensure_ascii=False))
    for highlight in enriched["highlights"]:
        candidate_id = highlight.get("candidate_id")
        if candidate_id not in candidates:
            raise RuntimeError(f"generation result contains unknown candidate {candidate_id!r}")
        candidate = candidates[candidate_id]
        highlight["source_start_ms"] = candidate["source_start_ms"]
        highlight["source_end_ms"] = candidate["source_end_ms"]
    return enriched


def _enrich_paired_generation(
    result: dict[str, Any],
    evidence: dict[str, Any],
    common_topics: dict[str, Any],
) -> dict[str, Any]:
    candidates = {item["candidate_id"]: item for item in evidence["candidates"]}
    topics = {item["topic_id"]: item for item in common_topics["topics"]}
    if set(result.get("topics", {})) != set(topics):
        raise RuntimeError("paired generation result does not cover the frozen topic set")
    enriched = json.loads(json.dumps(result, ensure_ascii=False))
    for topic_id, script in enriched["topics"].items():
        candidate_id = script.get("candidate_id")
        if candidate_id not in candidates:
            raise RuntimeError(f"paired result contains unknown candidate {candidate_id!r}")
        candidate = candidates[candidate_id]
        script["topic_label"] = topics[topic_id]["label"]
        script["topic_scope"] = topics[topic_id]["scope"]
        script["source_start_ms"] = candidate["source_start_ms"]
        script["source_end_ms"] = candidate["source_end_ms"]
    return enriched


def main() -> None:
    evidence = _load_evidence()
    frozen_path = EXPERIMENT_DIR / "frozen-input.json"
    _write_json(frozen_path, evidence)
    frozen_generation_schema = _frozen_generation_schema(evidence)
    generation_prompt = (
        GENERATION_PROMPT.read_text(encoding="utf-8")
        + "\n\n<untrusted_frozen_input>\n"
        + json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n</untrusted_frozen_input>\n"
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        terra_future = pool.submit(
            _run_codex,
            label="terra-medium",
            model="gpt-5.6-terra",
            effort="medium",
            prompt=generation_prompt,
            schema=frozen_generation_schema,
        )
        sol_future = pool.submit(
            _run_codex,
            label="sol-medium",
            model="gpt-5.6-sol",
            effort="medium",
            prompt=generation_prompt,
            schema=frozen_generation_schema,
        )
        terra, terra_metadata = terra_future.result()
        sol, sol_metadata = sol_future.result()

    _write_json(EXPERIMENT_DIR / "terra-medium.raw.json", terra)
    _write_json(EXPERIMENT_DIR / "sol-medium.raw.json", sol)
    terra = _enrich_generation(terra, evidence)
    sol = _enrich_generation(sol, evidence)
    _write_json(EXPERIMENT_DIR / "terra-medium.json", terra)
    _write_json(EXPERIMENT_DIR / "sol-medium.json", sol)

    # The judge only sees anonymous systems A and B. The mapping is disclosed after judging.
    judge_input = {"evidence": evidence, "system_a": terra, "system_b": sol}
    judge_prompt = (
        JUDGE_PROMPT.read_text(encoding="utf-8")
        + "\n\n<untrusted_blind_evaluation_input>\n"
        + json.dumps(judge_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n</untrusted_blind_evaluation_input>\n"
    )
    judge, judge_metadata = _run_codex(
        label="sol-max-judge",
        model="gpt-5.6-sol",
        effort="max",
        prompt=judge_prompt,
        schema=JUDGE_SCHEMA,
    )
    _write_json(EXPERIMENT_DIR / "sol-max-judge.json", judge)
    metadata = {
        "schema_version": "1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": evidence["source"],
        "blind_mapping_disclosed_after_judging": {
            "system_a": "gpt-5.6-terra / medium",
            "system_b": "gpt-5.6-sol / medium",
        },
        "calls": [terra_metadata, sol_metadata, judge_metadata],
        "artifact_sha256": {
            "frozen_input": _sha256(frozen_path),
            "terra_medium": _sha256(EXPERIMENT_DIR / "terra-medium.json"),
            "sol_medium": _sha256(EXPERIMENT_DIR / "sol-medium.json"),
            "sol_max_judge": _sha256(EXPERIMENT_DIR / "sol-max-judge.json"),
        },
    }
    _write_json(EXPERIMENT_DIR / "run-metadata.json", metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


def paired_main() -> None:
    evidence = _load_evidence()
    common_topics = json.loads(COMMON_TOPICS.read_text(encoding="utf-8"))
    paired_schema = _frozen_paired_generation_schema(evidence)
    paired_input = {"common_topics": common_topics, "evidence": evidence}
    generation_prompt = (
        PAIRED_GENERATION_PROMPT.read_text(encoding="utf-8")
        + "\n\n<untrusted_paired_input>\n"
        + json.dumps(paired_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n</untrusted_paired_input>\n"
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        terra_future = pool.submit(
            _run_codex,
            label="paired-terra-medium",
            model="gpt-5.6-terra",
            effort="medium",
            prompt=generation_prompt,
            schema=paired_schema,
        )
        sol_future = pool.submit(
            _run_codex,
            label="paired-sol-medium",
            model="gpt-5.6-sol",
            effort="medium",
            prompt=generation_prompt,
            schema=paired_schema,
        )
        terra_raw, terra_metadata = terra_future.result()
        sol_raw, sol_metadata = sol_future.result()

    _write_json(EXPERIMENT_DIR / "paired-terra-medium.raw.json", terra_raw)
    _write_json(EXPERIMENT_DIR / "paired-sol-medium.raw.json", sol_raw)
    terra = _enrich_paired_generation(terra_raw, evidence, common_topics)
    sol = _enrich_paired_generation(sol_raw, evidence, common_topics)
    _write_json(EXPERIMENT_DIR / "paired-terra-medium.json", terra)
    _write_json(EXPERIMENT_DIR / "paired-sol-medium.json", sol)

    judge_schema = _frozen_paired_judge_schema(common_topics, terra, sol)
    judge_input = {
        "common_topics": common_topics,
        "evidence": evidence,
        "system_a": terra,
        "system_b": sol,
    }
    judge_prompt = (
        PAIRED_JUDGE_PROMPT.read_text(encoding="utf-8")
        + "\n\n<untrusted_paired_evaluation_input>\n"
        + json.dumps(judge_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n</untrusted_paired_evaluation_input>\n"
    )
    judge, judge_metadata = _run_codex(
        label="paired-sol-max-judge",
        model="gpt-5.6-sol",
        effort="max",
        prompt=judge_prompt,
        schema=judge_schema,
    )
    _write_json(EXPERIMENT_DIR / "paired-sol-max-judge.json", judge)

    metadata = {
        "schema_version": "1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": evidence["source"],
        "method": "fixed-topic-paired-comparison",
        "topic_count": len(common_topics["topics"]),
        "blind_mapping_disclosed_after_judging": {
            "system_a": "gpt-5.6-terra / medium",
            "system_b": "gpt-5.6-sol / medium",
        },
        "calls": [terra_metadata, sol_metadata, judge_metadata],
        "artifact_sha256": {
            "common_topics": _sha256(COMMON_TOPICS),
            "paired_terra_medium": _sha256(EXPERIMENT_DIR / "paired-terra-medium.json"),
            "paired_sol_medium": _sha256(EXPERIMENT_DIR / "paired-sol-medium.json"),
            "paired_sol_max_judge": _sha256(EXPERIMENT_DIR / "paired-sol-max-judge.json"),
        },
    }
    _write_json(EXPERIMENT_DIR / "paired-run-metadata.json", metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if sys.argv[1:] == ["paired"]:
        paired_main()
    elif sys.argv[1:]:
        raise SystemExit("usage: run_experiment.py [paired]")
    else:
        main()
