#!/usr/bin/env python3
# ruff: noqa: RUF001
"""Audit frozen Highlight Agent Skill v1 evidence without calling a model.

The audit is intentionally read-only with respect to the benchmark. It classifies
every v1 ``highlight_sentence`` by where its normalized, continuous text can be
found and writes a new, immutable JSON/Markdown report directory.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BENCHMARK_ROOT = SCRIPT_DIR.parent / "model-benchmark-2026-08-17"
CONTRACTS_PATH = SCRIPT_DIR / "contracts.py"
ANALYSIS_FILENAME = "analysis.json"
EXPECTED_ANALYSIS_SHA256 = "fa7029c10b593a987b285132d241fcda7fb102ec26f45da4899c64d46575e2de"
EXPECTED_ARTIFACT_MANIFEST_COUNT = 343
EXPECTED_RESULT_COUNT = 30
EXPECTED_UNIQUE_SOURCE_COUNT = 3
EXPECTED_CONFIGS = {
    "terra_medium": ("gpt-5.6-terra", "medium"),
    "sol_medium": ("gpt-5.6-sol", "medium"),
    "sol_high": ("gpt-5.6-sol", "high"),
}
CLASSIFICATIONS = (
    "exact_candidate",
    "context_only",
    "other_candidate",
    "unsupported",
)
AUDIT_SCHEMA_VERSION = "liveclip-highlight-v1-offline-evidence-audit-v1"


def _load_contracts() -> Any:
    """Dynamically load the sibling research contract without changing sys.path."""

    spec = importlib.util.spec_from_file_location("liveclip_highlight_v2_contracts", CONTRACTS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load contracts module from {CONTRACTS_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CONTRACTS = _load_contracts()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"cannot read {path}: {exc}") from exc


def _load_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = _read_bytes(path)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"expected a JSON object in {path}")
    return value, _sha256_bytes(raw)


def _load_and_verify_artifact_manifest(benchmark_root: Path) -> dict[str, str]:
    analysis_path = benchmark_root / ANALYSIS_FILENAME
    analysis, analysis_sha256 = _load_json(analysis_path)
    if analysis_sha256 != EXPECTED_ANALYSIS_SHA256:
        raise RuntimeError(
            f"immutable benchmark analysis hash changed: {analysis_sha256}"
        )
    integrity = analysis.get("integrity")
    entries = integrity.get("artifact_manifest") if isinstance(integrity, dict) else None
    if not isinstance(entries, list) or len(entries) != EXPECTED_ARTIFACT_MANIFEST_COUNT:
        raise RuntimeError("benchmark artifact manifest count/shape is invalid")
    manifest: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise RuntimeError("benchmark artifact manifest contains an invalid entry")
        relative = entry["path"]
        expected_sha256 = entry["sha256"]
        if (
            not isinstance(relative, str)
            or not relative
            or relative.startswith("/")
            or ".." in Path(relative).parts
            or not isinstance(expected_sha256, str)
        ):
            raise RuntimeError("benchmark artifact manifest contains an unsafe path/hash")
        if relative in manifest:
            raise RuntimeError(f"duplicate artifact manifest path: {relative}")
        path = (benchmark_root / relative).resolve()
        if benchmark_root not in path.parents or not path.is_file():
            raise RuntimeError(f"manifest artifact is missing or escaped root: {relative}")
        actual_sha256 = _sha256_bytes(_read_bytes(path))
        if actual_sha256 != expected_sha256:
            raise RuntimeError(f"manifest artifact hash mismatch: {relative}")
        manifest[relative] = expected_sha256
    return manifest


def _require_manifest_hash(
    *, path: Path, benchmark_root: Path, actual_sha256: str, manifest: dict[str, str]
) -> None:
    relative = path.relative_to(benchmark_root).as_posix()
    if manifest.get(relative) != actual_sha256:
        raise RuntimeError(f"artifact is not bound to immutable manifest: {relative}")


def _normalized(value: str) -> str:
    # The receipt owns normalization semantics. Calling it against an empty
    # candidate exposes the exact normalized quote without duplicating rules.
    return str(CONTRACTS.exact_quote_receipt(value, "")["normalized_quote"])


def _exact_match(quote: str, value: str) -> dict[str, Any] | None:
    receipt = CONTRACTS.exact_quote_receipt(quote, value)
    return receipt if receipt["status"] == "passed" else None


def _approximate_coverage(quote: str, value: str) -> float:
    normalized_quote = _normalized(quote)
    normalized_value = _normalized(value)
    if not normalized_quote:
        return 0.0
    matcher = SequenceMatcher(None, normalized_quote, normalized_value, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return round(matched / len(normalized_quote), 4)


def _classify_highlight(
    highlight: dict[str, Any],
    candidates: list[dict[str, Any]],
    candidates_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidate_id = highlight.get("candidate_id")
    quote = highlight.get("highlight_sentence")
    if not isinstance(candidate_id, str) or candidate_id not in candidates_by_id:
        raise RuntimeError(f"result contains unknown candidate_id {candidate_id!r}")
    if not isinstance(quote, str) or not quote.strip():
        raise RuntimeError(f"candidate {candidate_id} has an empty highlight_sentence")

    bound = candidates_by_id[candidate_id]
    exact_matches: list[dict[str, Any]] = []

    receipt = _exact_match(quote, str(bound.get("text", "")))
    if receipt is not None:
        exact_matches.append(
            {
                "candidate_id": candidate_id,
                "field": "text",
                "receipt": receipt,
            }
        )
        category = "exact_candidate"
    else:
        for field in ("context_before", "context_after"):
            context_receipt = _exact_match(quote, str(bound.get(field, "")))
            if context_receipt is not None:
                exact_matches.append(
                    {
                        "candidate_id": candidate_id,
                        "field": field,
                        "receipt": context_receipt,
                    }
                )
        if exact_matches:
            category = "context_only"
        else:
            for other in candidates:
                other_id = other.get("candidate_id")
                if other_id == candidate_id:
                    continue
                other_receipt = _exact_match(quote, str(other.get("text", "")))
                if other_receipt is not None:
                    exact_matches.append(
                        {
                            "candidate_id": other_id,
                            "field": "text",
                            "receipt": other_receipt,
                        }
                    )
            category = "other_candidate" if exact_matches else "unsupported"

    approximate_targets: list[tuple[float, str, str]] = []
    for candidate in candidates:
        target_id = str(candidate["candidate_id"])
        for field in ("text", "context_before", "context_after"):
            value = str(candidate.get(field, ""))
            if not value:
                continue
            approximate_targets.append((_approximate_coverage(quote, value), target_id, field))
    best_coverage, best_candidate_id, best_field = max(
        approximate_targets,
        default=(0.0, candidate_id, "text"),
        key=lambda item: (item[0], item[1] == candidate_id, item[2] == "text"),
    )

    return {
        "candidate_id": candidate_id,
        "highlight_sentence": quote,
        "classification": category,
        "evidence_gate_passed": category == "exact_candidate",
        "exact_matches": exact_matches,
        "approximate_diagnostic": {
            "diagnostic_only": True,
            "counts_as_evidence_pass": False,
            "metric": "sequence-matcher-normalized-character-coverage",
            "best_coverage": best_coverage,
            "best_candidate_id": best_candidate_id,
            "best_field": best_field,
        },
    }


def _validate_frozen_binding(
    provenance: dict[str, Any],
    frozen_input: dict[str, Any],
    result_sha256: str,
    call_metadata: dict[str, Any],
    result_path: Path,
) -> None:
    source = frozen_input.get("source")
    if not isinstance(source, dict):
        raise RuntimeError(f"missing source object in input for {result_path}")
    for field in ("source_sha256", "rough_candidates_sha256", "transcript_sha256"):
        if source.get(field) != provenance.get(field):
            raise RuntimeError(f"{field} binding mismatch for {result_path}")
    expected_result_sha256 = call_metadata.get("result_sha256")
    if result_sha256 != expected_result_sha256:
        raise RuntimeError(
            f"result hash mismatch for {result_path}: "
            f"metadata={expected_result_sha256!r}, actual={result_sha256}"
        )


def _audit_result(
    result_path: Path, benchmark_root: Path, artifact_manifest: dict[str, str]
) -> dict[str, Any]:
    # .../<case>/<repeat>/generators/<config>/result.json
    try:
        relative_path = result_path.relative_to(benchmark_root)
    except ValueError as exc:
        raise RuntimeError(f"result escaped benchmark root: {result_path}") from exc
    parts = relative_path.parts
    if len(parts) != 6 or parts[0] != "results" or parts[3] != "generators":
        raise RuntimeError(f"unexpected benchmark result path: {relative_path}")
    _, case_id, repeat_id, _, config_id, _ = parts
    replicate_dir = result_path.parents[2]
    frozen_input_path = replicate_dir / "frozen-input.json"
    provenance_path = replicate_dir / "provenance.json"
    call_metadata_path = result_path.parent / "call-metadata.json"

    frozen_input, input_sha256 = _load_json(frozen_input_path)
    provenance, provenance_sha256 = _load_json(provenance_path)
    result, result_sha256 = _load_json(result_path)
    call_metadata, call_metadata_sha256 = _load_json(call_metadata_path)
    for path, actual_sha256 in (
        (frozen_input_path, input_sha256),
        (provenance_path, provenance_sha256),
        (result_path, result_sha256),
        (call_metadata_path, call_metadata_sha256),
    ):
        _require_manifest_hash(
            path=path,
            benchmark_root=benchmark_root,
            actual_sha256=actual_sha256,
            manifest=artifact_manifest,
        )
    _validate_frozen_binding(
        provenance,
        frozen_input,
        result_sha256,
        call_metadata,
        result_path,
    )
    if provenance.get("case_id") != case_id or provenance.get("replicate_id") != repeat_id:
        raise RuntimeError(f"path/provenance identity mismatch for {result_path}")
    expected_model = EXPECTED_CONFIGS.get(config_id)
    if expected_model is None or (
        call_metadata.get("model"), call_metadata.get("reasoning_effort")
    ) != expected_model:
        raise RuntimeError(f"config/model/effort mismatch for {result_path}")
    unsafe_receipt = call_metadata.get("unsafe_tool_event")
    reused_without_receipt = call_metadata.get("reused") is True and unsafe_receipt is None
    if unsafe_receipt is not False and not reused_without_receipt:
        raise RuntimeError(f"unsafe tool receipt is not false for {result_path}")

    candidates = frozen_input.get("candidates")
    highlights = result.get("highlights")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError(f"missing candidates in {frozen_input_path}")
    if not isinstance(highlights, list) or not highlights:
        raise RuntimeError(f"missing highlights in {result_path}")
    if any(not isinstance(candidate, dict) for candidate in candidates):
        raise RuntimeError(f"invalid candidate in {frozen_input_path}")
    candidates_by_id = {candidate.get("candidate_id"): candidate for candidate in candidates}
    if len(candidates_by_id) != len(candidates) or None in candidates_by_id:
        raise RuntimeError(f"candidate IDs are missing or duplicated in {frozen_input_path}")
    candidate_order_sha256 = _sha256_bytes(
        CONTRACTS.canonical_json_bytes([candidate["candidate_id"] for candidate in candidates])
    )
    if provenance.get("candidate_order_sha256") != candidate_order_sha256:
        raise RuntimeError(f"candidate-order hash mismatch for {result_path}")

    audited_highlights = [
        _classify_highlight(highlight, candidates, candidates_by_id)
        for highlight in highlights
        if isinstance(highlight, dict)
    ]
    if len(audited_highlights) != len(highlights):
        raise RuntimeError(f"invalid highlight object in {result_path}")
    counts = Counter(item["classification"] for item in audited_highlights)
    complete_counts = {name: counts.get(name, 0) for name in CLASSIFICATIONS}
    gate_pass_count = complete_counts["exact_candidate"]

    return {
        "source_sha256": provenance["source_sha256"],
        "source_aliases": provenance.get("source_aliases", []),
        "case_id": case_id,
        "evidence_key": provenance.get("evidence_key"),
        "benchmark_role": provenance.get("benchmark_role"),
        "include_in_primary_aggregate": bool(provenance.get("include_in_primary_aggregate", False)),
        "config_id": config_id,
        "model": call_metadata.get("model"),
        "reasoning_effort": call_metadata.get("reasoning_effort"),
        "repeat_id": repeat_id,
        "candidate_count": len(candidates),
        "highlight_count": len(audited_highlights),
        "classification_counts": complete_counts,
        "exact_candidate_rate": round(gate_pass_count / len(audited_highlights), 6),
        "hash_binding": {
            "source_sha256": provenance["source_sha256"],
            "input_file_sha256": input_sha256,
            "result_file_sha256": result_sha256,
            "result_metadata_sha256": call_metadata["result_sha256"],
            "provenance_file_sha256": provenance_sha256,
            "call_metadata_file_sha256": call_metadata_sha256,
            "rough_candidates_sha256": provenance.get("rough_candidates_sha256"),
            "transcript_sha256": provenance.get("transcript_sha256"),
            "candidate_order_sha256": candidate_order_sha256,
        },
        "paths": {
            "input": frozen_input_path.relative_to(benchmark_root).as_posix(),
            "result": result_path.relative_to(benchmark_root).as_posix(),
            "provenance": provenance_path.relative_to(benchmark_root).as_posix(),
        },
        "highlights": audited_highlights,
    }


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter()
    highlight_count = 0
    for record in records:
        counts.update(record["classification_counts"])
        highlight_count += int(record["highlight_count"])
    complete_counts = {name: counts.get(name, 0) for name in CLASSIFICATIONS}
    exact_count = complete_counts["exact_candidate"]
    return {
        "output_count": len(records),
        "highlight_count": highlight_count,
        "classification_counts": complete_counts,
        "exact_candidate_rate": round(exact_count / highlight_count, 6) if highlight_count else 0.0,
    }


def _build_aggregates(records: list[dict[str, Any]]) -> dict[str, Any]:
    primary = [record for record in records if record["include_in_primary_aggregate"]]
    diagnostics = [record for record in records if not record["include_in_primary_aggregate"]]

    source_config_repeat = [
        {
            "source_sha256": record["source_sha256"],
            "case_id": record["case_id"],
            "config_id": record["config_id"],
            "repeat_id": record["repeat_id"],
            "include_in_primary_aggregate": record["include_in_primary_aggregate"],
            **_aggregate([record]),
        }
        for record in records
    ]

    grouped_source_config: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    grouped_config: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in primary:
        grouped_source_config[(record["source_sha256"], record["config_id"])].append(record)
        grouped_config[record["config_id"]].append(record)

    source_config = [
        {
            "source_sha256": source_sha256,
            "config_id": config_id,
            **_aggregate(group),
        }
        for (source_sha256, config_id), group in sorted(grouped_source_config.items())
    ]
    by_config = [
        {"config_id": config_id, **_aggregate(group)}
        for config_id, group in sorted(grouped_config.items())
    ]

    return {
        "weighting_policy": (
            "Each generator output has weight 1. source_aliases are descriptive only and "
            "are never expanded into samples. Records with "
            "include_in_primary_aggregate=false are audited but excluded from primary totals."
        ),
        "by_source_config_repeat": source_config_repeat,
        "primary_by_source_config": source_config,
        "primary_by_config": by_config,
        "primary_overall": _aggregate(primary),
        "diagnostic_overall": _aggregate(diagnostics),
        "all_audited_overall": _aggregate(records),
    }


def audit(benchmark_root: Path) -> dict[str, Any]:
    benchmark_root = benchmark_root.resolve()
    artifact_manifest = _load_and_verify_artifact_manifest(benchmark_root)
    results_root = benchmark_root / "results"
    if not results_root.is_dir():
        raise RuntimeError(f"benchmark results directory does not exist: {results_root}")
    result_paths = sorted(results_root.glob("*/r*/generators/*/result.json"))
    if len(result_paths) != EXPECTED_RESULT_COUNT:
        raise RuntimeError(
            f"expected {EXPECTED_RESULT_COUNT} frozen v1 results, found {len(result_paths)}"
        )
    records = [
        _audit_result(path, benchmark_root, artifact_manifest) for path in result_paths
    ]
    unique_sources = {record["source_sha256"] for record in records}
    if len(unique_sources) != EXPECTED_UNIQUE_SOURCE_COUNT:
        raise RuntimeError(
            f"expected {EXPECTED_UNIQUE_SOURCE_COUNT} unique sources, found {len(unique_sources)}"
        )
    primary_sources = {
        record["source_sha256"] for record in records if record["include_in_primary_aggregate"]
    }
    if primary_sources != unique_sources:
        raise RuntimeError("primary records do not cover every unique source exactly as expected")

    contracts_bytes = _read_bytes(CONTRACTS_PATH)
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "method": {
            "mode": "zero-model-offline",
            "model_calls": 0,
            "classification_precedence": list(CLASSIFICATIONS),
            "passing_classification": "exact_candidate",
            "normalization_contract": CONTRACTS.QUOTE_VALIDATOR_VERSION,
            "contract_version": CONTRACTS.CONTRACT_VERSION,
            "contracts_sha256": _sha256_bytes(contracts_bytes),
            "benchmark_analysis_sha256": EXPECTED_ANALYSIS_SHA256,
            "verified_artifact_manifest_count": len(artifact_manifest),
            "approximate_diagnostic": (
                "SequenceMatcher normalized-character coverage is diagnostic only and never "
                "changes a classification or evidence-gate result."
            ),
        },
        "scope": {
            "audited_output_count": len(records),
            "unique_source_count": len(unique_sources),
            "case_count": len({record["case_id"] for record in records}),
            "config_count": len({record["config_id"] for record in records}),
            "primary_output_count": sum(
                1 for record in records if record["include_in_primary_aggregate"]
            ),
            "diagnostic_output_count": sum(
                1 for record in records if not record["include_in_primary_aggregate"]
            ),
        },
        "aggregates": _build_aggregates(records),
        "outputs": records,
    }


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return lines


def render_markdown(report: dict[str, Any], audit_json_sha256: str) -> str:
    scope = report["scope"]
    aggregates = report["aggregates"]
    lines = [
        "# Highlight Agent Skill v1 离线证据审计",
        "",
        f"生成时间：`{report['generated_at']}`",
        "",
        "本报告没有调用模型。只有高光语句在其绑定候选正文中形成规范化后的连续精确子串，才通过证据门；近似相似度只作诊断，永不计为通过。",
        "",
        f"审计 JSON SHA-256：`{audit_json_sha256}`",
        "",
        "## 范围与权重",
        "",
        (
            f"- 审计输出：{scope['audited_output_count']}"
            f"（主样本 {scope['primary_output_count']}，"
            f"诊断变体 {scope['diagnostic_output_count']}）"
        ),
        (
            f"- 唯一源视频：{scope['unique_source_count']}；"
            f"case：{scope['case_count']}；配置：{scope['config_count']}"
        ),
        (
            "- 每份生成结果权重为 1；source aliases 仅用于描述，不展开计数。"
            "ASR 敏感性变体被审计，但不进入主汇总。"
        ),
        "",
        "## 主汇总（按配置）",
        "",
    ]
    config_rows = []
    for item in aggregates["primary_by_config"]:
        counts = item["classification_counts"]
        config_rows.append(
            [
                item["config_id"],
                item["output_count"],
                item["highlight_count"],
                counts["exact_candidate"],
                counts["context_only"],
                counts["other_candidate"],
                counts["unsupported"],
                f"{100 * item['exact_candidate_rate']:.2f}%",
            ]
        )
    lines.extend(
        _markdown_table(
            [
                "配置",
                "输出",
                "语句",
                "绑定正文精确",
                "仅上下文",
                "其他候选",
                "不支持",
                "通过率",
            ],
            config_rows,
        )
    )
    lines.extend(["", "## Source / 配置 / Repeat 明细", ""])
    detail_rows = []
    for item in aggregates["by_source_config_repeat"]:
        counts = item["classification_counts"]
        detail_rows.append(
            [
                item["source_sha256"][:12],
                item["case_id"],
                item["config_id"],
                item["repeat_id"],
                "主样本" if item["include_in_primary_aggregate"] else "诊断",
                item["highlight_count"],
                counts["exact_candidate"],
                counts["context_only"],
                counts["other_candidate"],
                counts["unsupported"],
                f"{100 * item['exact_candidate_rate']:.2f}%",
            ]
        )
    lines.extend(
        _markdown_table(
            [
                "源 SHA",
                "Case",
                "配置",
                "Repeat",
                "范围",
                "语句",
                "正文精确",
                "上下文",
                "其他候选",
                "不支持",
                "通过率",
            ],
            detail_rows,
        )
    )
    overall = aggregates["primary_overall"]
    lines.extend(
        [
            "",
            "## 结论边界",
            "",
            (
                f"主样本共 {overall['highlight_count']} 条高光语句，"
                "绑定候选正文精确通过率为 "
                f"{100 * overall['exact_candidate_rate']:.2f}%。"
            ),
            (
                "context_only 和 other_candidate 表示文本虽可在冻结输入中找到，"
                "但证据绑定错误；两者均不通过。unsupported 包括改写、拼接或"
                "无法找到连续精确证据的语句。"
            ),
            "",
            (
                "完整逐句分类、精确匹配 receipt、源/input/result 哈希绑定及"
                "只读近似诊断见 `audit.json`。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise RuntimeError(f"refusing to overwrite existing output directory: {output_dir}")
    parent = output_dir.parent
    if not parent.is_dir():
        raise RuntimeError(f"output parent directory does not exist: {parent}")

    json_bytes = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    json_sha256 = _sha256_bytes(json_bytes)
    markdown = render_markdown(report, json_sha256)

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=str(output_dir.parent))
    )
    try:
        (temporary / "audit.json").write_bytes(json_bytes)
        (temporary / "README.md").write_text(markdown, encoding="utf-8")
        temporary.rename(output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    json_path = output_dir / "audit.json"
    markdown_path = output_dir / "README.md"
    return json_path, markdown_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit all 30 frozen Highlight Agent Skill v1 outputs without model calls. "
            "The output directory must not already exist."
        )
    )
    parser.add_argument(
        "--benchmark-root",
        type=Path,
        default=DEFAULT_BENCHMARK_ROOT,
        help=f"Frozen benchmark root (default: {DEFAULT_BENCHMARK_ROOT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New directory for audit.json and README.md; existing paths are rejected",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(args.benchmark_root)
        json_path, markdown_path = write_report(report, args.output_dir)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"audited_outputs={report['scope']['audited_output_count']}")
    print(f"unique_sources={report['scope']['unique_source_count']}")
    print(f"json={json_path}")
    print(f"markdown={markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
