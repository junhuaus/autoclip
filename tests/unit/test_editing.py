from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from liveclip.domain.candidate import CandidateClip
from liveclip.pipeline.editing import edit_and_rank_candidates
from liveclip.providers.llm.base import (
    LLMDisposition,
    LLMProviderResult,
    deterministic_edit_plan,
)


def _candidate(index: int, score: float) -> CandidateClip:
    start = index * 10_000
    return CandidateClip(
        candidate_id=f"candidate_{index}",
        source_start_ms=start,
        source_end_ms=start + 10_000,
        allowed_start_ms=start,
        allowed_end_ms=start + 10_000,
        text=f"第{index}个完整观点。",
        rule_score=score,
        reasons=("complete_sentence",),
        segment_ids=(f"segment_{index}",),
    )


@dataclass
class _ScoringProvider:
    scores: dict[str, float]
    fail_first: bool = False
    calls: int = 0

    @property
    def provider_name(self) -> str:
        return "test"

    @property
    def model_name(self) -> str:
        return "test-editor-v1"

    @property
    def prompt_version(self) -> str:
        return "editing_v1"

    @property
    def prompt_sha256(self) -> str:
        return "a" * 64

    @property
    def contract_version(self) -> str:
        return "test-contract-v1"

    def edit_candidate(
        self,
        candidate: CandidateClip,
        *,
        source_duration_ms: int,
        minimum_duration_ms: int,
        maximum_duration_ms: int,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> LLMProviderResult:
        del cancel_requested
        self.calls += 1
        failed = self.fail_first and self.calls == 1
        plan = deterministic_edit_plan(
            candidate,
            source_duration_ms=source_duration_ms,
            minimum_duration_ms=minimum_duration_ms,
            maximum_duration_ms=maximum_duration_ms,
            model=self.model_name,
            prompt_version=self.prompt_version,
            degraded=failed,
            risk_flags=("provider_error",) if failed else ("test",),
        ).model_copy(update={"score": self.scores[candidate.candidate_id]})
        return LLMProviderResult(
            plan=plan,
            disposition=(LLMDisposition.PROVIDER_ERROR if failed else LLMDisposition.SUCCEEDED),
        )


def _run(provider: _ScoringProvider, candidates: tuple[CandidateClip, ...], cache: Path):
    return edit_and_rank_candidates(
        provider,
        candidates,
        source_duration_ms=60_000,
        minimum_duration_ms=5_000,
        maximum_duration_ms=20_000,
        top_n=1,
        cache_dir=cache,
    )


def test_ai_scores_every_rough_candidate_before_top_n(tmp_path: Path) -> None:
    candidates = (_candidate(0, 90), _candidate(1, 20), _candidate(2, 10))
    provider = _ScoringProvider(scores={"candidate_0": 5, "candidate_1": 30, "candidate_2": 99})

    result = _run(provider, candidates, tmp_path)

    assert provider.calls == 3
    assert result.selected[0].candidate.candidate_id == "candidate_2"


def test_per_candidate_cache_prevents_duplicate_provider_calls(tmp_path: Path) -> None:
    candidates = (_candidate(0, 50), _candidate(1, 40))
    first = _ScoringProvider(scores={"candidate_0": 70, "candidate_1": 80})
    _run(first, candidates, tmp_path)
    replay_events: list[bool] = []
    replay = _ScoringProvider(scores={"candidate_0": 1, "candidate_1": 2})

    result = edit_and_rank_candidates(
        replay,
        candidates,
        source_duration_ms=60_000,
        minimum_duration_ms=5_000,
        maximum_duration_ms=20_000,
        top_n=1,
        cache_dir=tmp_path,
        on_call_records=lambda _records, cache_hit: replay_events.append(cache_hit),
    )

    assert replay.calls == 0
    assert all(item.cache_hit for item in result.all_results)
    assert result.selected[0].candidate.candidate_id == "candidate_1"
    assert replay_events == []  # Test provider has no cloud call evidence.


def test_provider_error_opens_circuit_for_remaining_candidates(tmp_path: Path) -> None:
    candidates = (_candidate(0, 50), _candidate(1, 40), _candidate(2, 30))
    provider = _ScoringProvider(
        scores={"candidate_0": 50, "candidate_1": 40, "candidate_2": 30},
        fail_first=True,
    )

    result = _run(provider, candidates, tmp_path)

    assert provider.calls == 1
    assert all(item.result.plan.degraded for item in result.all_results)
    assert result.all_results[1].result.plan.risk_flags == ("ai_provider_circuit_open",)
    assert not tuple(tmp_path.glob("*.json"))


def test_tampered_editing_cache_fails_before_provider_call(tmp_path: Path) -> None:
    candidates = (_candidate(0, 50),)
    _run(_ScoringProvider(scores={"candidate_0": 70}), candidates, tmp_path)
    cache_path = next(tmp_path.glob("candidate-*.json"))
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["result"]["plan"]["score"] = 1
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    provider = _ScoringProvider(scores={"candidate_0": 99})

    with pytest.raises(ValueError, match="immutable input identity"):
        _run(provider, candidates, tmp_path)

    assert provider.calls == 0


def test_editing_cache_rejects_symlink_before_provider_call(tmp_path: Path) -> None:
    candidates = (_candidate(0, 50),)
    _run(_ScoringProvider(scores={"candidate_0": 70}), candidates, tmp_path)
    cache_path = next(tmp_path.glob("candidate-*.json"))
    outside = tmp_path / "outside.json"
    outside.write_bytes(cache_path.read_bytes())
    cache_path.unlink()
    cache_path.symlink_to(outside)
    provider = _ScoringProvider(scores={"candidate_0": 99})

    with pytest.raises(ValueError, match="trusted record"):
        _run(provider, candidates, tmp_path)

    assert provider.calls == 0
