# High-recall Discovery v2 repair delta

修复结构时不得按分数、top_n、风险或预期发布状态删减候选。保留 candidate 到输入 batch、逻辑
窗口、topic 和 evidence cue 的完整可追踪关系。只修复当前 batch，不重新解释其他 batch。
