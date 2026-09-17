# Discovery v4

对输入中的每个逻辑窗口分别做高召回覆盖检查，同时利用去重后的 batch 上下文理解局部内容。
同一候选在一个 batch 中只输出一次；候选开始 cue 必须归属输入 ownership interval，但该规则
只决定记录归属，不是语义去重。

输出每个窗口的 `left_boundary`、`right_boundary`，以及所有有潜在价值的 `topic_fragments` 和
候选。Fragment 要说明中心问题、学习结果、左右是否完整、是否触碰边界、证据 cue 和可能的
Profile。不得按 75 分、Top-N、发布风险或最终边界是否已满足时长提前删除。医学、商业、演唱、
地域、年龄、外貌、隐私或 ASR 不确定内容仍需发现并记录风险线索。

只返回 DiscoveryBatchOutputV4 Schema。不要把具体输入时间或话术当作固定规则。
