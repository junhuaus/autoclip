from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("analyze_benchmark.py")
SPEC = importlib.util.spec_from_file_location("liveclip_benchmark_analysis", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ANALYSIS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYSIS)


class AnalysisMetricTests(unittest.TestCase):
    def test_candidate_jaccard(self) -> None:
        self.assertEqual(ANALYSIS.candidate_jaccard([], []), 1.0)
        self.assertAlmostEqual(
            ANALYSIS.candidate_jaccard(["a", "b"], ["b", "c"]),
            1 / 3,
        )

    def test_interval_match_uses_maximum_cardinality(self) -> None:
        result = ANALYSIS.interval_match(
            [(0, 100), (100, 200)],
            [(0, 100), (100, 200), (300, 400)],
        )
        self.assertEqual(result["matches"], 2)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 0.6667)
        self.assertEqual(result["f1"], 0.8)

    def test_adjusted_rand_is_label_invariant(self) -> None:
        left = {"a": "x", "b": "x", "c": "y", "d": "y"}
        right = {"a": "2", "b": "2", "c": "1", "d": "1"}
        self.assertEqual(ANALYSIS.adjusted_rand_index(left, right), 1.0)
        self.assertEqual(ANALYSIS.co_cluster_f1(left, right)["f1"], 1.0)

    def test_partition_entity_mismatch_fails(self) -> None:
        with self.assertRaises(ANALYSIS.AnalysisError):
            ANALYSIS.adjusted_rand_index({"a": "x"}, {"b": "x"})

    def test_quote_alignment_recomputes_runner_threshold(self) -> None:
        exact = ANALYSIS.quote_alignment("你好,世界!", "开头你好世界结尾")
        self.assertEqual(exact["status"], "exact")
        failed = ANALYSIS.quote_alignment("完全不同的一句话", "唱歌需要呼吸")
        self.assertEqual(failed["status"], "failed")

    def test_weighted_total_is_calculated_not_supplied(self) -> None:
        atomics = {
            "topic_discovery": 4,
            "evidence_fidelity": 3,
            "clip_selection": 2,
            "editorial_usability": 1,
            "portfolio_quality": 0,
        }
        self.assertEqual(ANALYSIS._score_system(atomics), 58.8)

    def test_scale_and_family_bias_diagnostics_are_deterministic(self) -> None:
        analyzer = object.__new__(ANALYSIS.BenchmarkAnalyzer)
        analyzer.generator_configs = {
            "terra_medium": {},
            "sol_medium": {},
            "sol_high": {},
        }
        analyzer.judge_configs = {"terra_max": {}, "sol_max": {}}
        all_four = {name: 4 for name in ANALYSIS.ATOMIC_WEIGHTS}
        all_three = {name: 3 for name in ANALYSIS.ATOMIC_WEIGHTS}
        record = {
            "case_id": "source-a",
            "judges": {
                "sol_max": {
                    "computed_total_by_model": {
                        "terra_medium": 75.0,
                        "sol_medium": 100.0,
                        "sol_high": 100.0,
                    },
                    "atomic_scores_by_model": {
                        "terra_medium": all_three,
                        "sol_medium": all_four,
                        "sol_high": all_four,
                    },
                },
                "terra_max": {
                    "computed_total_by_model": {
                        "terra_medium": 75.0,
                        "sol_medium": 75.0,
                        "sol_high": 75.0,
                    },
                    "atomic_scores_by_model": {
                        "terra_medium": all_three,
                        "sol_medium": all_three,
                        "sol_high": all_three,
                    },
                },
            },
        }
        scale = analyzer._judge_scale_diagnostics([record])
        self.assertEqual(scale["sol_max"]["total_100_ceiling_rate"], 0.6667)
        self.assertEqual(scale["sol_max"]["pairwise_total_tie_rate"], 0.3333)
        bias = analyzer._judge_bias([record])
        self.assertEqual(bias["sol_family_probe"]["difference_in_differences"], 25.0)


if __name__ == "__main__":
    unittest.main()
