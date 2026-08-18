#!/usr/bin/env python3
# ruff: noqa: E501, RUF001
"""Generate the offline Chinese HTML report for the LiveClip model benchmark.

The report is a presentation layer only.  All quantitative claims come from
``analysis.json``; this script deliberately refuses to run when that aggregate
is missing or incomplete.  Per-topic editorial text is read from the immutable
judge/generator artifacts so it remains inspectable without duplicating it into
the aggregate.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ANALYSIS = BASE_DIR / "analysis.json"
DEFAULT_NARRATIVE = BASE_DIR / "report-narrative.json"
DEFAULT_OUTPUT = BASE_DIR / "REPORT.html"
REQUIRED_ANALYSIS_KEYS = {
    "protocol",
    "completeness",
    "main",
    "configs",
    "by_source",
    "by_replicate",
    "pairwise",
    "judges",
    "topics",
    "diagnostic",
    "limitations",
}
REQUIRED_NARRATIVE_KEYS = {
    "schema_version",
    "analysis_sha256",
    "created_at",
    "executive_conclusion",
    "model_recommendation",
    "skill_recommendations",
    "limitations",
    "next_eval",
}

CONFIG_LABELS = {
    "terra_medium": "Terra · Medium",
    "sol_medium": "Sol · Medium",
    "sol_high": "Sol · High",
}
JUDGE_LABELS = {
    "terra_max": "Terra · Max Judge",
    "sol_max": "Sol · Max Judge",
}
KEY_LABELS = {
    "aggregate": "聚合",
    "agreement": "一致性",
    "atomic": "原子维度",
    "avg": "平均",
    "by_config": "按配置",
    "by_judge": "按 Judge",
    "by_source": "按唯一源视频",
    "candidate_jaccard": "候选 Jaccard",
    "completeness": "完整性",
    "config": "配置",
    "count": "数量",
    "diagnostic": "D1 诊断",
    "duration_seconds": "耗时（秒）",
    "elapsed_seconds": "耗时（秒）",
    "failed_quote_count": "Quote 失败数",
    "failed_quote_rate": "Quote 失败率",
    "interval_f1": "区间匹配 F1",
    "judge": "Judge",
    "judge_consensus_total": "双 Judge 共识总分",
    "macro": "主样本宏平均",
    "mean": "均值",
    "median": "中位数",
    "model": "模型",
    "output_tokens": "输出 Tokens",
    "pair": "配置对",
    "primary": "主样本",
    "reasoning_effort": "Reasoning Effort",
    "reasoning_tokens": "Reasoning Tokens",
    "replicate": "重复实验",
    "score": "分数",
    "selected_count": "选中数量",
    "source": "唯一源视频",
    "status": "状态",
    "sol_max_total": "Sol · Max 原始总分",
    "terra_max_total": "Terra · Max 原始总分",
    "top1": "第一名",
    "total": "总分",
}


@dataclass(frozen=True)
class TopicMember:
    config_id: str
    anonymous_system_id: str
    highlight_id: str
    candidate_id: str
    title: str
    proposed_topic: str
    highlight_sentence: str
    assessment: str
    scores: dict[str, Any]


@dataclass(frozen=True)
class TopicCluster:
    case_id: str
    replicate_id: str
    judge_id: str
    cluster_id: str
    canonical_topic: str
    confidence: str
    assessment: str
    members: tuple[TopicMember, ...]
    result_path: Path


def load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise SystemExit(f"缺少报告输入：{path}。请先完整运行 benchmark analyzer。") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"报告输入不是合法 JSON：{path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _summarize_replicates(replicates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for replicate in replicates:
        generators = replicate.get("generators", {})
        consensus = replicate.get("judge_consensus", {})
        models: dict[str, Any] = {}
        for config_id, generation in generators.items():
            usage = generation.get("usage", {})
            quote_alignment = generation.get("quote_alignment", {})
            models[config_id] = {
                "judge_consensus_total": consensus.get(config_id, {}).get("total"),
                "selected_count": generation.get("selected_count"),
                "elapsed_seconds": generation.get("elapsed_seconds"),
                "output_tokens": usage.get("output_tokens"),
                "reasoning_tokens": usage.get("reasoning_output_tokens"),
                "quote_failed_rate": quote_alignment.get("failed_rate"),
            }
        summaries.append(
            {
                "case_id": replicate.get("case_id"),
                "replicate": replicate.get("replicate_id"),
                "candidate_order": replicate.get("candidate_order"),
                "models": models,
                "dual_judge_agreement": replicate.get("dual_judge_agreement"),
            }
        )
    return summaries


def _summarize_topics(replicates: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total_clusters = 0
    for replicate in replicates:
        for judge_id, judge in replicate.get("judges", {}).items():
            count = judge.get("cluster_count")
            if isinstance(count, int):
                total_clusters += count
            rows.append(
                {
                    "case_id": replicate.get("case_id"),
                    "replicate": replicate.get("replicate_id"),
                    "judge": judge_id,
                    "cluster_count": count,
                    "topic_count_by_model": judge.get("topic_count_by_model"),
                    "semantic_duplicate_rate_by_model": judge.get(
                        "semantic_duplicate_rate_by_model"
                    ),
                    "pairwise_semantic_jaccard": judge.get("pairwise_semantic_jaccard"),
                }
            )
    return {
        "judge_topic_cluster_observations": total_clusters,
        "note": (
            "The count sums each judge partition independently; it is not a count of "
            "unique real-world topics."
        ),
        "by_replicate_and_judge": rows,
    }


def _collect_judge_limitations(replicates: list[dict[str, Any]]) -> list[str]:
    limitations: list[str] = []
    seen: set[str] = set()
    for replicate in replicates:
        for judge in replicate.get("judges", {}).values():
            raw = judge.get("limitations", [])
            values = raw if isinstance(raw, list) else [raw]
            for value in values:
                text = str(value).strip()
                if text and text not in seen:
                    limitations.append(text)
                    seen.add(text)
    return limitations


def normalize_analysis(analysis: dict[str, Any], path: Path) -> dict[str, Any]:
    """Normalize supported analyzer schemas into report sections without rescoring."""
    if analysis.keys() >= REQUIRED_ANALYSIS_KEYS:
        return analysis

    analyzer_keys = {"integrity", "scope", "primary", "diagnostics"}
    if not analyzer_keys <= analysis.keys():
        expected = "、".join(sorted(analyzer_keys))
        raise SystemExit(f"{path} 不是受支持的 analyzer schema；至少需要：{expected}。")

    integrity = analysis["integrity"]
    if not isinstance(integrity, dict) or integrity.get("status") != "passed":
        raise SystemExit("analysis.json integrity.status 不是 passed；拒绝生成正式报告。")
    for expected_key, validated_key in (
        ("expected_generator_outputs", "validated_generator_outputs"),
        ("expected_judge_outputs", "validated_judge_outputs"),
    ):
        expected = integrity.get(expected_key)
        validated = integrity.get(validated_key)
        if expected != validated:
            raise SystemExit(
                f"analysis.json {validated_key}={validated!r}，不等于 {expected_key}={expected!r}。"
            )

    primary = analysis["primary"]
    if not isinstance(primary, dict) or not isinstance(primary.get("macro"), dict):
        raise SystemExit("analysis.json primary.macro 缺失；拒绝生成正式报告。")
    macro = primary["macro"]
    replicates = primary.get("replicates", [])
    if not isinstance(replicates, list):
        raise SystemExit("analysis.json primary.replicates 必须是 list。")
    models = macro.get("models", {})

    quote_summary: dict[str, Any] = {}
    efficiency_summary: dict[str, Any] = {}
    for config_id, model in models.items():
        generation = model.get("generation", {})
        quote_summary[config_id] = {
            key: generation.get(key)
            for key in (
                "quote_exact_rate",
                "quote_failed_rate",
                "quote_mean_character_coverage",
            )
        }
        quote_summary[config_id]["raw_counts"] = model.get("quote_raw_counts")
        efficiency_summary[config_id] = {
            key: generation.get(key)
            for key in (
                "elapsed_seconds",
                "input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
                "selected_count",
            )
        }

    scope_limitations = analysis.get("scope", {}).get("limitations", [])
    limitations = list(scope_limitations) if isinstance(scope_limitations, list) else []
    limitations.extend(_collect_judge_limitations(replicates))
    diagnostics = analysis["diagnostics"]
    diagnostic_cases = diagnostics.get("cases", []) if isinstance(diagnostics, dict) else []
    if isinstance(diagnostic_cases, list):
        limitations.extend(_collect_judge_limitations(diagnostic_cases))
    limitations = list(dict.fromkeys(str(item) for item in limitations if str(item).strip()))
    diagnostic_summary = {
        "excluded_from_primary_aggregate": diagnostics.get(
            "excluded_from_primary_aggregate"
        ),
        "cases": _summarize_replicates(diagnostic_cases),
        "same_source_evidence_sensitivity": diagnostics.get(
            "same_source_evidence_sensitivity"
        ),
    }
    return {
        "schema_version": analysis.get("schema_version"),
        "generated_at": analysis.get("generated_at"),
        "protocol": analysis["scope"],
        "completeness": {
            key: value for key, value in integrity.items() if key != "artifact_manifest"
        },
        "main": macro,
        "configs": models,
        "by_source": primary.get("by_source", {}),
        "by_replicate": {
            "macro_replicate_stability": macro.get("replicate_stability"),
            "replicates": _summarize_replicates(replicates),
        },
        "pairwise": {
            "paired_comparisons": macro.get("paired_comparisons"),
            "cross_configuration_overlap": macro.get("cross_configuration_overlap"),
        },
        "judges": macro.get("dual_judge_agreement", {}),
        "topics": {
            "macro_topic_metrics": macro.get("topic_metrics"),
            "observed_partitions": _summarize_topics(replicates),
        },
        "diagnostic": diagnostic_summary,
        "limitations": limitations,
        "quotes": quote_summary,
        "efficiency": {
            "generator_configurations": efficiency_summary,
            "judge_runtime": macro.get("judge_runtime"),
        },
        "_raw_analysis_schema": "analyzer-v1",
    }


def require_analysis(analysis: Any, path: Path) -> dict[str, Any]:
    if not isinstance(analysis, dict):
        raise SystemExit(f"{path} 顶层必须是 JSON object。")
    analysis = normalize_analysis(analysis, path)
    missing = sorted(REQUIRED_ANALYSIS_KEYS - analysis.keys())
    if missing:
        joined = "、".join(missing)
        raise SystemExit(f"{path} 尚未完整，缺少顶层字段：{joined}。拒绝生成不完整报告。")

    completeness = analysis["completeness"]
    if isinstance(completeness, dict):
        ready = completeness.get("ready_for_report")
        if ready is False:
            raise SystemExit("analysis.json 标记 ready_for_report=false；拒绝生成不完整报告。")
        status = str(completeness.get("status", "")).lower()
        if status in {"failed", "incomplete", "partial", "running"}:
            raise SystemExit(f"analysis.json 完整性状态为 {status!r}；拒绝生成报告。")
    return analysis


def _require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"report-narrative.json {context} 必须是非空 string。")
    return value


def require_narrative(narrative: Any, path: Path, analysis_path: Path) -> dict[str, Any]:
    if not isinstance(narrative, dict):
        raise SystemExit(f"{path} 顶层必须是 JSON object。")
    missing = sorted(REQUIRED_NARRATIVE_KEYS - narrative.keys())
    if missing:
        raise SystemExit(
            "report-narrative.json 缺少字段：" + "、".join(missing) + "。拒绝生成正式报告。"
        )
    if narrative.get("schema_version") != "1":
        raise SystemExit("report-narrative.json schema_version 必须为 '1'。")
    expected_hash = sha256_file(analysis_path)
    if narrative.get("analysis_sha256") != expected_hash:
        raise SystemExit(
            "report-narrative.json analysis_sha256 与当前 analysis.json 不一致；"
            "请基于最新确定性分析重写工程建议。"
        )
    _require_string(narrative.get("created_at"), "created_at")
    conclusions = narrative.get("executive_conclusion")
    if not isinstance(conclusions, list) or not conclusions:
        raise SystemExit("report-narrative.json executive_conclusion 必须是非空 string list。")
    for index, value in enumerate(conclusions):
        _require_string(value, f"executive_conclusion[{index}]")
    recommendation = narrative.get("model_recommendation")
    if not isinstance(recommendation, dict):
        raise SystemExit("report-narrative.json model_recommendation 必须是 object。")
    for key in ("default", "escalation", "budget_tier", "rationale"):
        _require_string(recommendation.get(key), f"model_recommendation.{key}")
    skill_items = narrative.get("skill_recommendations")
    if not isinstance(skill_items, list) or not skill_items:
        raise SystemExit("report-narrative.json skill_recommendations 必须是非空 list。")
    for index, item in enumerate(skill_items):
        if not isinstance(item, dict):
            raise SystemExit(f"skill_recommendations[{index}] 必须是 object。")
        for key in ("priority", "tier", "change", "evidence", "validation"):
            _require_string(item.get(key), f"skill_recommendations[{index}].{key}")
    limitations = narrative.get("limitations")
    if not isinstance(limitations, list):
        raise SystemExit("report-narrative.json limitations 必须是 string list。")
    for index, value in enumerate(limitations):
        _require_string(value, f"limitations[{index}]")
    next_eval = narrative.get("next_eval")
    if not isinstance(next_eval, list) or not next_eval:
        raise SystemExit("report-narrative.json next_eval 必须是非空 list。")
    for index, item in enumerate(next_eval):
        if not isinstance(item, dict):
            raise SystemExit(f"next_eval[{index}] 必须是 object。")
        for key in ("priority", "action", "success_criteria"):
            _require_string(item.get(key), f"next_eval[{index}].{key}")
    return narrative


def e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def label(key: str) -> str:
    return KEY_LABELS.get(key, key.replace("_", " "))


def config_label(config_id: str) -> str:
    return CONFIG_LABELS.get(config_id, config_id)


def display_scalar(value: Any, *, key: str = "") -> str:
    if value is None:
        return '<span class="muted">—</span>'
    if isinstance(value, bool):
        return '<span class="pill good">是</span>' if value else '<span class="pill bad">否</span>'
    if isinstance(value, float):
        suffix = "%" if "rate" in key and 0 <= value <= 1 else ""
        number = value * 100 if suffix else value
        rendered = f"{number:.3f}".rstrip("0").rstrip(".")
        return f"{e(rendered)}{suffix}"
    if isinstance(value, int):
        return f"{value:,}"
    text = str(value)
    css_class = "mono" if len(text) >= 24 and " " not in text else ""
    return f'<span class="{css_class}">{e(text)}</span>'


def common_columns(rows: list[dict[str, Any]]) -> list[str]:
    preferred = [
        "config",
        "config_id",
        "source",
        "case_id",
        "replicate",
        "judge",
        "score",
        "total",
        "mean",
        "count",
    ]
    seen: set[str] = set()
    columns: list[str] = []
    for key in preferred:
        if any(key in row for row in rows):
            columns.append(key)
            seen.add(key)
    for row in rows:
        for key in row:
            if key not in seen:
                columns.append(key)
                seen.add(key)
    return columns


def render_table(rows: list[dict[str, Any]], *, css_class: str = "") -> str:
    if not rows:
        return '<p class="empty">无数据</p>'
    columns = common_columns(rows)
    head = "".join(f"<th>{e(label(column))}</th>" for column in columns)
    body: list[str] = []
    for row in rows:
        cells: list[str] = []
        for column in columns:
            value = row.get(column)
            if column in {"config", "config_id"} and isinstance(value, str):
                value = config_label(value)
            if isinstance(value, (dict, list)):
                rendered = render_value(value, depth=1)
            else:
                rendered = display_scalar(value, key=column)
            cells.append(f"<td>{rendered}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f'<div class="table-scroll {e(css_class)}"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def dict_as_rows(value: dict[str, Any]) -> list[dict[str, Any]] | None:
    if not value:
        return []
    if not all(isinstance(item, dict) for item in value.values()):
        return None
    return [{"id": key, **item} for key, item in value.items()]


def render_value(value: Any, *, depth: int = 0) -> str:
    if isinstance(value, dict):
        rows = dict_as_rows(value)
        if rows is not None and rows:
            return render_table(rows)
        parts: list[str] = []
        for key, item in value.items():
            parts.append(
                '<div class="kv-row">'
                f'<div class="kv-key">{e(label(str(key)))}</div>'
                f'<div class="kv-value">{render_value(item, depth=depth + 1)}</div>'
                "</div>"
            )
        return '<div class="kv">' + "".join(parts) + "</div>"
    if isinstance(value, list):
        if not value:
            return '<span class="muted">空</span>'
        if all(isinstance(item, dict) for item in value):
            return render_table(value)
        return '<ul class="compact">' + "".join(
            f"<li>{render_value(item, depth=depth + 1)}</li>" for item in value
        ) + "</ul>"
    return display_scalar(value)


def section(section_id: str, title: str, intro: str, body: str) -> str:
    return (
        f'<section id="{e(section_id)}" class="panel">'
        f"<h2>{e(title)}</h2>"
        f'<p class="section-intro">{e(intro)}</p>'
        f"{body}</section>"
    )


def source_alias_rows(cases: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_sets = cases.get("evidence_sets", {})
    rows: list[dict[str, Any]] = []
    for evidence_id, evidence in evidence_sets.items():
        if not isinstance(evidence, dict):
            continue
        rows.append(
            {
                "evidence_id": evidence_id,
                "role": evidence.get("benchmark_role"),
                "source_label": evidence.get("source_label"),
                "aliases": " = ".join(evidence.get("source_aliases", [])),
                "sha256": evidence.get("expected_source_sha256"),
                "run_id": evidence.get("run_id"),
            }
        )
    return rows


def config_rows(protocol: dict[str, Any], analysis: dict[str, Any]) -> list[dict[str, Any]]:
    config_analysis = analysis.get("configs", {})
    rows: list[dict[str, Any]] = []
    for config_id, spec in protocol.get("generator_models", {}).items():
        metrics = config_analysis.get(config_id, {}) if isinstance(config_analysis, dict) else {}
        consensus = metrics.get("judge_consensus", {})
        raw = metrics.get("judge_raw", {})
        generation = metrics.get("generation", {})
        row: dict[str, Any] = {
            "config": config_id,
            "model": spec.get("model"),
            "reasoning_effort": spec.get("effort"),
            "judge_consensus_total": consensus.get("total"),
            "terra_max_total": raw.get("terra_max", {}).get("total"),
            "sol_max_total": raw.get("sol_max", {}).get("total"),
            "selected_count": generation.get("selected_count"),
            "quote_failed_rate": generation.get("quote_failed_rate"),
            "elapsed_seconds": generation.get("elapsed_seconds"),
            "output_tokens": generation.get("output_tokens"),
            "reasoning_tokens": generation.get("reasoning_output_tokens"),
        }
        rows.append(row)
    return rows


def atomic_score_rows(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config_id, metrics in analysis.get("configs", {}).items():
        consensus = metrics.get("judge_consensus", {})
        atomics = consensus.get("atomic_scores", {})
        rows.append(
            {
                "config": config_id,
                "total": consensus.get("total"),
                **atomics,
            }
        )
    return rows


def source_details_html(by_source: Any) -> str:
    if not isinstance(by_source, dict) or not by_source:
        return render_value(by_source)
    sections: list[str] = []
    for case_id, source in by_source.items():
        model_rows: list[dict[str, Any]] = []
        for config_id, metrics in source.get("models", {}).items():
            consensus = metrics.get("judge_consensus", {})
            generation = metrics.get("generation", {})
            model_rows.append(
                {
                    "config": config_id,
                    "judge_consensus_total": consensus.get("total"),
                    "selected_count": generation.get("selected_count"),
                    "elapsed_seconds": generation.get("elapsed_seconds"),
                    "output_tokens": generation.get("output_tokens"),
                    "reasoning_tokens": generation.get("reasoning_output_tokens"),
                    "quote_failed_rate": generation.get("quote_failed_rate"),
                }
            )
        supporting = {
            "stability": source.get("stability"),
            "cross_configuration": source.get("cross_configuration"),
            "dual_judge_agreement": source.get("dual_judge_agreement"),
        }
        aliases = " = ".join(source.get("source_aliases", []))
        sections.append(
            '<details class="source-group" open>'
            f"<summary>{e(source.get('source_label', case_id))}"
            f'<span class="count">{e(aliases)}</span></summary>'
            '<div class="source-body">'
            + render_table(model_rows)
            + '<h4>稳定性、跨配置重合与 Judge 一致性</h4>'
            + render_value(supporting)
            + "</div></details>"
        )
    return "".join(sections)


def relative_href(path: Path) -> str:
    try:
        relative = path.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return ""
    return quote(relative, safe="/._-")


def generator_lookup(replicate_dir: Path) -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = {}
    for result_path in sorted((replicate_dir / "generators").glob("*/result.json")):
        result = load_json(result_path)
        highlights = result.get("highlights", []) if isinstance(result, dict) else []
        lookup[result_path.parent.name] = highlights if isinstance(highlights, list) else []
    return lookup


def collect_topic_clusters() -> list[TopicCluster]:
    clusters: list[TopicCluster] = []
    for result_path in sorted(BASE_DIR.glob("results/*/*/judges/*/result.json")):
        replicate_dir = result_path.parents[2]
        case_id = replicate_dir.parent.name
        replicate_id = replicate_dir.name
        judge_id = result_path.parent.name
        mapping_path = result_path.parent / "mapping.disclosed-after-judging.json"
        if not mapping_path.exists():
            continue
        result = load_json(result_path)
        mapping = load_json(mapping_path)
        systems = mapping.get("anonymous_system_mapping", {})
        generators = generator_lookup(replicate_dir)

        for cluster in result.get("clusters", []):
            members: list[TopicMember] = []
            for member in cluster.get("members", []):
                anonymous_id = str(member.get("anonymous_system_id", ""))
                config_id = str(systems.get(anonymous_id, anonymous_id))
                highlight_id = str(member.get("highlight_id", ""))
                try:
                    position = int(highlight_id.removeprefix("h")) - 1
                except ValueError:
                    position = -1
                highlights = generators.get(config_id, [])
                generated = highlights[position] if 0 <= position < len(highlights) else {}
                scores = {
                    key: value
                    for key, value in member.items()
                    if key
                    not in {
                        "anonymous_system_id",
                        "highlight_id",
                        "candidate_id",
                        "assessment",
                    }
                }
                members.append(
                    TopicMember(
                        config_id=config_id,
                        anonymous_system_id=anonymous_id,
                        highlight_id=highlight_id,
                        candidate_id=str(member.get("candidate_id", "")),
                        title=str(generated.get("title", "")),
                        proposed_topic=str(generated.get("topic", "")),
                        highlight_sentence=str(generated.get("highlight_sentence", "")),
                        assessment=str(member.get("assessment", "")),
                        scores=scores,
                    )
                )
            clusters.append(
                TopicCluster(
                    case_id=case_id,
                    replicate_id=replicate_id,
                    judge_id=judge_id,
                    cluster_id=str(cluster.get("cluster_id", "")),
                    canonical_topic=str(cluster.get("canonical_topic", "")),
                    confidence=str(cluster.get("alignment_confidence", "")),
                    assessment=str(cluster.get("assessment", "")),
                    members=tuple(members),
                    result_path=result_path,
                )
            )
    return clusters


def topic_member_html(member: TopicMember) -> str:
    score_bits = "".join(
        f'<span class="score-chip">{e(label(key))} {display_scalar(value, key=key)}</span>'
        for key, value in member.scores.items()
    )
    title = member.title or "（原生成结果未提供标题）"
    proposed = f" · 原 Topic：{e(member.proposed_topic)}" if member.proposed_topic else ""
    quote_text = member.highlight_sentence or "（原生成结果未提供高光语句）"
    return (
        '<article class="member-card">'
        '<div class="member-head">'
        f'<strong>{e(config_label(member.config_id))}</strong>'
        f'<span class="pill">{e(member.anonymous_system_id)} / {e(member.highlight_id)}</span>'
        "</div>"
        f'<h4>{e(title)}{proposed}</h4>'
        f'<p class="quote">“{e(quote_text)}”</p>'
        f'<p><strong>Judge 评价：</strong>{e(member.assessment)}</p>'
        f'<div class="scores">{score_bits}</div>'
        f'<p class="micro mono">{e(member.candidate_id)}</p>'
        "</article>"
    )


def topic_cluster_html(cluster: TopicCluster) -> str:
    member_configs = ", ".join(config_label(member.config_id) for member in cluster.members)
    search = " ".join(
        [cluster.canonical_topic, cluster.assessment]
        + [member.title + " " + member.highlight_sentence for member in cluster.members]
    )
    return (
        f'<article class="topic-card" data-search="{e(search.lower())}">'
        '<div class="topic-head">'
        f"<h3>{e(cluster.canonical_topic or cluster.cluster_id)}</h3>"
        f'<span class="pill confidence-{e(cluster.confidence)}">{e(cluster.confidence or "未标记")}</span>'
        "</div>"
        f'<p class="micro">{e(cluster.cluster_id)} · {e(member_configs)}</p>'
        f'<p>{e(cluster.assessment)}</p>'
        '<div class="member-grid">'
        + "".join(topic_member_html(member) for member in cluster.members)
        + "</div></article>"
    )


def topic_details_html(clusters: list[TopicCluster]) -> str:
    if not clusters:
        return '<p class="empty">尚无完整双 Judge Topic artifact。</p>'
    grouped: dict[tuple[str, str, str], list[TopicCluster]] = defaultdict(list)
    for cluster in clusters:
        grouped[(cluster.case_id, cluster.replicate_id, cluster.judge_id)].append(cluster)
    details: list[str] = []
    for (case_id, replicate_id, judge_id), group in grouped.items():
        result_path = group[0].result_path
        details.append(
            '<details class="topic-group">'
            "<summary>"
            f"{e(case_id)} · {e(replicate_id)} · {e(JUDGE_LABELS.get(judge_id, judge_id))}"
            f'<span class="count">{len(group)} Topics</span>'
            "</summary>"
            '<div class="topic-list">'
            + "".join(topic_cluster_html(cluster) for cluster in group)
            + "</div>"
            f'<p class="artifact-link"><a href="{e(relative_href(result_path))}">查看 Judge 原始 JSON</a></p>'
            "</details>"
        )
    return "".join(details)


def report_timestamp(analysis: dict[str, Any]) -> str:
    for key in ("generated_at", "created_at", "analyzed_at"):
        if analysis.get(key):
            return str(analysis[key])
    return datetime.now().astimezone().isoformat(timespec="seconds")


def recommendation_html(narrative: dict[str, Any]) -> str:
    return (
        '<div class="recommendation-label">工程评估建议 · 非确定性 analyzer 输出</div>'
        '<h4>执行结论</h4>'
        + render_value(narrative["executive_conclusion"])
        + '<h4>模型配置建议</h4>'
        + render_value(narrative["model_recommendation"])
    )


def artifact_rows(analysis_path: Path, narrative_path: Path) -> list[dict[str, Any]]:
    paths = [
        analysis_path,
        narrative_path,
        BASE_DIR / "protocol.json",
        BASE_DIR / "cases.json",
        BASE_DIR / "agent-v1" / "SKILL.md",
        BASE_DIR / "schemas" / "highlight-output.schema.json",
        BASE_DIR / "prompts" / "judge-v1.md",
        BASE_DIR / "schemas" / "judge-output.schema.json",
        BASE_DIR / "run-summary.json",
    ]
    rows: list[dict[str, Any]] = []
    for path in paths:
        if path.exists():
            href = relative_href(path)
            try:
                display_path = path.relative_to(BASE_DIR).as_posix()
            except ValueError:
                display_path = str(path)
            rows.append(
                {
                    "artifact": path.name,
                    "path": display_path,
                    "size_bytes": path.stat().st_size,
                    "link": href,
                }
            )
    return rows


def artifact_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">无 artifact。</p>'
    body_rows: list[str] = []
    for row in rows:
        link = (
            f'<a href="{e(row["link"])}">打开</a>'
            if row["link"]
            else '<span class="muted">目录外输入</span>'
        )
        body_rows.append(
            "<tr>"
            f"<td>{e(row['artifact'])}</td>"
            f"<td class=\"mono\">{e(row['path'])}</td>"
            f"<td>{int(row['size_bytes']):,}</td>"
            f"<td>{link}</td>"
            "</tr>"
        )
    body = "".join(body_rows)
    return (
        '<div class="table-scroll"><table><thead><tr>'
        "<th>Artifact</th><th>相对路径</th><th>字节数</th><th>链接</th>"
        f"</tr></thead><tbody>{body}</tbody></table></div>"
    )


def build_html(
    analysis: dict[str, Any],
    narrative: dict[str, Any],
    protocol: dict[str, Any],
    cases: dict[str, Any],
    analysis_path: Path,
    narrative_path: Path,
) -> str:
    clusters = collect_topic_clusters()
    primary_cases = [case for case in cases.get("cases", []) if case.get("include_in_primary_aggregate")]
    diagnostic_cases = [case for case in cases.get("cases", []) if not case.get("include_in_primary_aggregate")]
    config_count = len(protocol.get("generator_models", {}))
    judge_count = len(protocol.get("judge_models", {}))
    topic_count = len(clusters)

    nav_items = [
        ("overview", "研究总览"),
        ("scores", "模型分数"),
        ("sources", "每 Source"),
        ("pairwise", "差值与重合"),
        ("replicates", "顺序扰动"),
        ("quotes", "Quote 证据"),
        ("judges", "双 Judge"),
        ("topics", "逐 Topic"),
        ("diagnostic", "D1 诊断"),
        ("efficiency", "速度 / Tokens"),
        ("skill", "Skill 建议"),
        ("limits", "限制与 Artifacts"),
    ]
    nav = "".join(f'<a href="#{e(anchor)}">{e(title)}</a>' for anchor, title in nav_items)

    caveats = """
    <div class="guardrail-grid">
      <div class="guardrail"><strong>样本权重</strong><span>输入文件名之间存在 byte-identical alias，本轮只有 3 个唯一 source；主结论按 source 宏平均，alias 不重复计权，D1 权重为 0。</span></div>
      <div class="guardrail"><strong>配置身份</strong><span>这是 3 个推理配置，不是 3 个独立模型：Sol · Medium 与 Sol · High 共用 gpt-5.6-sol。</span></div>
      <div class="guardrail"><strong>发现方式</strong><span>完全自由发现 Topic；没有预设 Topic 清单，也没有把旧固定 Topic 实验纳入本报告。</span></div>
      <div class="guardrail"><strong>盲审</strong><span>Terra · Max 与 Sol · Max 双 Judge；候选系统匿名化，映射仅在成功判分后披露。</span></div>
      <div class="guardrail"><strong>测量对象</strong><span>当前测的是“批量组合选择 Agent”，不是生产链路里逐候选 EditPlan Agent。</span></div>
      <div class="guardrail"><strong>不能回答</strong><span>没有人工绝对真值 inventory；且 3 个唯一样本均为同类声乐直播，不能外推到多品类直播。</span></div>
    </div>
    """

    alias_body = (
        '<h3>唯一 Source 与 Alias</h3>'
        + render_table(source_alias_rows(cases), css_class="alias-table")
        + '<p class="footnote">相同 SHA-256 代表同一媒体内容。D1 是同一 source 的旧证据链，'
        "仅用于证据敏感性诊断。</p>"
    )
    overview = section(
        "overview",
        "研究总览",
        "先界定本测试能回答什么，避免把文件名、推理 effort 或诊断样本误当成独立数据点。",
        caveats + alias_body + '<h3>分析完整性</h3>' + render_value(analysis["completeness"]),
    )

    scores = section(
        "scores",
        "模型配置分数与综合建议",
        "总分由 analyzer 按 source-first 规则计算；展示层不重算、不补值，也不硬编码胜者。",
        '<h3>三项生成配置</h3>'
        + render_table(config_rows(protocol, analysis))
        + '<h3>双 Judge 共识原子分</h3>'
        + render_table(atomic_score_rows(analysis))
        + '<p class="footnote">主样本均先在 replicate 内平均双 Judge，再在 source 内平均，'
        "最后对 3 个唯一 source 等权宏平均。其余稳定性和重合指标见后续章节。</p>"
        + '<h3>工程评估建议</h3>'
        + recommendation_html(narrative),
    )

    sources = section(
        "sources",
        "每个唯一 Source 的结果",
        "逐 source 展示可防止一个长视频或高产 replicate 主导整体平均。Alias 不另起一行。",
        source_details_html(analysis["by_source"]),
    )
    pairwise = section(
        "pairwise",
        "Pair Delta 与 Topic / Candidate 重合",
        "比较同一 source 下配置间的成对差值、完全相同候选和语义 Topic 重合。缺失 Topic 表示该配置未选择，不等同于质量零分。",
        render_value(analysis["pairwise"]),
    )
    replicates = section(
        "replicates",
        "候选顺序扰动与重复一致性",
        "r001 / r002 / r003 分别使用原序、倒序和确定性 shuffle；每个顺序只有一次调用，因此这里测的是“顺序扰动 + 采样”的联合一致性，不是纯因果顺序效应。",
        render_value(analysis["by_replicate"]),
    )

    quote_value = analysis.get("quotes")
    if quote_value is None and isinstance(analysis.get("configs"), dict):
        quote_value = {
            key: {
                metric: value
                for metric, value in config.items()
                if "quote" in metric or "alignment" in metric
            }
            for key, config in analysis["configs"].items()
            if isinstance(config, dict)
        }
    quotes = section(
        "quotes",
        "Quote 与候选证据对齐",
        "Quote 指标检查高光语句是否能在所属候选证据中对齐。它受句子长度与编辑式改写影响，不能单独等同于内容质量。",
        render_value(quote_value or {"status": "analysis.json 未提供独立 quote 聚合"}),
    )
    judges = section(
        "judges",
        "双 Judge 一致性与偏差",
        "保留 Terra · Max 与 Sol · Max 的原始差异；共识分不能遮蔽 Judge 偏好、Topic 分簇敏感性或排名分歧。",
        '<div class="callout caution"><strong>量表天花板：</strong>'
        "0–4 原子量表聚合后可能出现 100 分或并列。100 仅表示该 Judge 在当前候选集、"
        "当前量表下各项均给满分，不是绝对完美或人工真值。应同时查看 analysis 中的 "
        "ceiling / tie 指标、原子分和另一位 Judge。</div>"
        + render_value(analysis["judges"]),
    )

    topics = section(
        "topics",
        "逐 Topic 盲审记录",
        f"analysis.json 的 Topic 汇总在前；其后展开 {topic_count} 个 Judge Topic cluster。每条均反匿名映射回生成配置，同时保留 Judge 原话。",
        '<h3>Topic 聚合</h3>'
        + render_value(analysis["topics"])
        + '<h3>逐 Case / Replicate / Judge 详情</h3>'
        + topic_details_html(clusters),
    )
    diagnostic = section(
        "diagnostic",
        "D1：同源旧证据链敏感性",
        "D1 不进入主分。它同时改变 transcript 与 rough candidate intervals，因此只能称为“完整证据管线敏感性”，不能隔离成纯 ASR 效应。",
        render_value(analysis["diagnostic"]),
    )

    efficiency_value = analysis.get("efficiency") or analysis.get("runtime")
    if efficiency_value is None and isinstance(analysis.get("configs"), dict):
        interesting = {"duration_seconds", "latency", "output_tokens", "reasoning_tokens", "tokens"}
        efficiency_value = {
            key: {metric: value for metric, value in config.items() if metric in interesting}
            for key, config in analysis["configs"].items()
            if isinstance(config, dict)
        }
    efficiency = section(
        "efficiency",
        "速度与 Tokens",
        "耗时和 token 是本机 Codex 子进程的实测值；没有配置价格时不估算费用。",
        render_value(efficiency_value or {"status": "analysis.json 未提供独立效率聚合"}),
    )

    skill_value = narrative["skill_recommendations"]
    skill_body = (
        '<div class="recommendation-label">工程评估建议 · 非确定性 analyzer 输出</div>'
        '<div class="callout">'
        "<strong>建议优先采用任务分级，而非品类分支：</strong>"
        "Tier 0 确定性证据门 → Tier 1 候选评估 → Tier 2 自由 Topic 盘点与去重 → "
        "Tier 3 组合选择 → Tier 4 编辑文案 → Tier 5 独立审计。"
        "</div>"
        + render_value(skill_value)
    )
    skill = section(
        "skill",
        "Agent Skill 分级改进建议",
        "将证据约束、自由发现、组合优化与文案编辑拆开，便于按失败类型升级模型 effort，也便于分别测试。",
        skill_body,
    )

    artifacts = artifact_table(artifact_rows(analysis_path, narrative_path))
    limits = section(
        "limits",
        "限制、适用边界与原始 Artifacts",
        "报告保留负面证据与不可验证项；任何生产模型替换都应再做逐候选集成评估和人工编辑验收。",
        '<h3>确定性分析限制</h3>'
        + render_value(analysis["limitations"])
        + '<h3>工程评估补充限制</h3>'
        + render_value(narrative["limitations"])
        + '<h3>下一轮验证</h3>'
        + render_value(narrative["next_eval"])
        + '<h3>可审计 Artifacts</h3>'
        + artifacts
        + '<p class="footnote">逐 Topic 区域另有每个 Judge result.json 的直接链接。'
        '所有链接均为相对路径，可随整个目录离线搬运。</p>',
    )

    html_document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LiveClip 三配置自由发现 Benchmark 报告</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #15222d;
      --muted: #687680;
      --paper: #f6f2ea;
      --panel: #fffdf8;
      --line: #d9d2c6;
      --accent: #006d77;
      --accent-soft: #d9f0ef;
      --warm: #b45309;
      --warm-soft: #fff0d3;
      --good: #176b3a;
      --bad: #a33030;
      --shadow: 0 12px 34px rgba(55, 45, 35, .08);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 2% 0%, rgba(0, 109, 119, .11), transparent 30rem),
        var(--paper);
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "PingFang SC",
        "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      line-height: 1.62;
    }}
    a {{ color: var(--accent); text-underline-offset: 3px; }}
    .hero {{
      padding: 68px max(24px, calc((100vw - 1200px) / 2));
      color: #f8fffe;
      background: linear-gradient(125deg, #073b4c, #006d77 68%, #0a9396);
    }}
    .eyebrow {{ margin: 0 0 10px; letter-spacing: .12em; text-transform: uppercase; opacity: .78; }}
    h1 {{ max-width: 900px; margin: 0; font-size: clamp(2.25rem, 6vw, 4.8rem); line-height: 1.03; }}
    .subtitle {{ max-width: 830px; margin: 24px 0 0; font-size: 1.15rem; opacity: .9; }}
    .hero-meta {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 28px; }}
    .hero-meta span {{ padding: 6px 12px; border: 1px solid rgba(255,255,255,.32); border-radius: 99px; }}
    .nav {{
      position: sticky; top: 0; z-index: 10; display: flex; gap: 8px; overflow-x: auto;
      padding: 12px max(18px, calc((100vw - 1200px) / 2)); background: rgba(255,253,248,.94);
      border-bottom: 1px solid var(--line); backdrop-filter: blur(14px);
    }}
    .nav a {{ flex: 0 0 auto; padding: 7px 11px; color: var(--ink); text-decoration: none; border-radius: 8px; }}
    .nav a:hover {{ color: var(--accent); background: var(--accent-soft); }}
    main {{ max-width: 1200px; margin: 34px auto 80px; padding: 0 22px; }}
    .panel {{ margin: 0 0 28px; padding: clamp(22px, 4vw, 42px); background: var(--panel); border: 1px solid var(--line); border-radius: 18px; box-shadow: var(--shadow); }}
    h2 {{ margin: 0; font-size: clamp(1.55rem, 3vw, 2.2rem); line-height: 1.2; }}
    h3 {{ margin: 32px 0 12px; font-size: 1.2rem; }}
    h4 {{ margin: 8px 0; font-size: 1rem; }}
    .section-intro {{ max-width: 920px; margin: 10px 0 26px; color: var(--muted); }}
    .guardrail-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
    .guardrail {{ padding: 16px; background: #f2f7f6; border-left: 4px solid var(--accent); border-radius: 9px; }}
    .guardrail strong, .guardrail span {{ display: block; }}
    .guardrail span {{ margin-top: 5px; color: #42535d; font-size: .94rem; }}
    .table-scroll {{ width: 100%; overflow-x: auto; border: 1px solid var(--line); border-radius: 10px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .91rem; }}
    th, td {{ padding: 11px 12px; vertical-align: top; text-align: left; border-bottom: 1px solid #e8e2d9; }}
    th {{ position: sticky; top: 0; color: #f9ffff; background: #315b61; white-space: nowrap; }}
    tr:last-child td {{ border-bottom: 0; }}
    tbody tr:nth-child(even) {{ background: #fbf8f2; }}
    .kv {{ border-top: 1px solid var(--line); }}
    .kv-row {{ display: grid; grid-template-columns: minmax(150px, .28fr) 1fr; gap: 18px; padding: 10px 0; border-bottom: 1px solid var(--line); }}
    .kv-key {{ color: var(--muted); font-weight: 700; overflow-wrap: anywhere; }}
    .kv-value {{ min-width: 0; overflow-wrap: anywhere; }}
    .compact {{ margin: 4px 0; padding-left: 22px; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }}
    .muted, .micro, .footnote, .empty {{ color: var(--muted); }}
    .micro {{ margin: 3px 0; font-size: .79rem; }}
    .footnote {{ font-size: .88rem; }}
    .pill {{ display: inline-block; padding: 2px 8px; border: 1px solid #a8c6c5; border-radius: 99px; background: var(--accent-soft); font-size: .76rem; white-space: nowrap; }}
    .pill.good {{ color: var(--good); }}
    .pill.bad {{ color: var(--bad); background: #fde4e4; border-color: #efbaba; }}
    .confidence-medium, .confidence-low {{ color: var(--warm); background: var(--warm-soft); border-color: #eac481; }}
    .callout {{ margin: 14px 0; padding: 16px 18px; background: var(--accent-soft); border-radius: 10px; }}
    .callout.caution {{ background: var(--warm-soft); }}
    .recommendation-label {{
      display: inline-block; margin: 4px 0 10px; padding: 5px 9px; color: #744106;
      background: var(--warm-soft); border: 1px solid #eac481; border-radius: 6px;
      font-size: .78rem; font-weight: 750; letter-spacing: .025em;
    }}
    details.topic-group {{ margin: 12px 0; border: 1px solid var(--line); border-radius: 11px; background: #fff; }}
    details.topic-group > summary {{ cursor: pointer; padding: 14px 16px; font-weight: 750; }}
    details.topic-group[open] > summary {{ border-bottom: 1px solid var(--line); }}
    details.source-group {{ margin: 14px 0; border: 1px solid var(--line); border-radius: 11px; background: #fff; }}
    details.source-group > summary {{ cursor: pointer; padding: 14px 16px; font-weight: 750; }}
    details.source-group[open] > summary {{ border-bottom: 1px solid var(--line); }}
    .source-body {{ padding: 16px; }}
    .count {{ float: right; color: var(--muted); font-size: .85rem; font-weight: 500; }}
    .topic-list {{ padding: 14px; }}
    .topic-card {{ margin: 0 0 14px; padding: 18px; border: 1px solid #d9e5e4; border-radius: 11px; background: #fafdfe; }}
    .topic-head, .member-head {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; }}
    .topic-head h3 {{ margin: 0; }}
    .member-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 14px; }}
    .member-card {{ min-width: 0; padding: 14px; border: 1px solid var(--line); border-radius: 9px; background: #fff; }}
    .quote {{ color: #263e45; padding-left: 11px; border-left: 3px solid #84b9b6; }}
    .scores {{ display: flex; flex-wrap: wrap; gap: 5px; }}
    .score-chip {{ padding: 2px 6px; color: #394951; background: #eef3f3; border-radius: 5px; font-size: .72rem; }}
    .artifact-link {{ margin: 0 16px 16px; }}
    footer {{ padding: 28px; color: var(--muted); text-align: center; }}
    @media (max-width: 920px) {{
      .guardrail-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .member-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 620px) {{
      .hero {{ padding-top: 46px; padding-bottom: 46px; }}
      .guardrail-grid {{ grid-template-columns: 1fr; }}
      .kv-row {{ grid-template-columns: 1fr; gap: 4px; }}
      .panel {{ border-radius: 12px; }}
      th, td {{ padding: 9px; }}
    }}
    @media print {{
      .nav {{ display: none; }}
      body {{ background: white; }}
      .panel {{ break-inside: avoid; box-shadow: none; }}
      details {{ break-inside: avoid; }}
      details > * {{ display: block !important; }}
    }}
  </style>
</head>
<body>
  <header class="hero">
    <p class="eyebrow">LiveClip · Model &amp; Agent Skill Evaluation</p>
    <h1>三项配置，自由发现高光 Topic</h1>
    <p class="subtitle">对 3 个唯一直播源进行批量高光组合选择，并以双盲双 Judge 审查质量、重合、稳定性、证据忠实度与成本。</p>
    <div class="hero-meta">
      <span>{len(primary_cases)} 个主 source</span>
      <span>{len(diagnostic_cases)} 个 D1 诊断 case</span>
      <span>{config_count} 项生成配置</span>
      <span>{judge_count} 个 Max Judge</span>
      <span>{e(report_timestamp(analysis))}</span>
    </div>
  </header>
  <nav class="nav" aria-label="报告章节">{nav}</nav>
  <main>
    {overview}
    {scores}
    {sources}
    {pairwise}
    {replicates}
    {quotes}
    {judges}
    {topics}
    {diagnostic}
    {efficiency}
    {skill}
    {limits}
  </main>
  <footer>LiveClip benchmark · 离线自包含报告 · 数值来源：analysis.json</footer>
</body>
</html>
"""
    return html_document


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--narrative", type=Path, default=DEFAULT_NARRATIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    analysis_path = args.analysis.resolve()
    narrative_path = args.narrative.resolve()
    output_path = args.output.resolve()
    analysis = require_analysis(load_json(analysis_path), analysis_path)
    narrative = require_narrative(
        load_json(narrative_path), narrative_path, analysis_path
    )
    protocol = load_json(BASE_DIR / "protocol.json")
    cases = load_json(BASE_DIR / "cases.json")
    document = build_html(
        analysis,
        narrative,
        protocol,
        cases,
        analysis_path,
        narrative_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(document, encoding="utf-8")
    temporary.replace(output_path)
    print(f"已生成：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
