# Global Review v4

只审核同一个 Clip Profile 的候选，不与另一 Profile 排名竞争。输入包含实际连续候选字幕、
前后局部上下文、Topic Chain、Boundary Review、风险和来源 cue。执行同 Profile 远距离语义
去重、标题/摘要来源忠实度、完整性、教学/传播价值和发布风险判断。评分只能针对 Boundary
Review 后的真实连续区间，不能针对设想的 jump cut。

当前 Global Review 中，`boundary_reviews` 提供的是已经解决边界问题的最终 Boundary 区间。
必须独立判断该给定的精确区间，不得照抄上游历史 `repair_boundary` 决定。
该精确区间可接受时，`content_decision` 返回 `keep`，否则返回 `drop`。
即使其他通用或 Profile 指导讨论边界调整，当前 Global Review 也不得返回 `repair_boundary`，
不得提出第二次边界修复。

short_highlight 使用既有 20/20/15/20/15/10 评分；mini_lesson 使用中心目标20、完整闭合20、
教学推进15、独立理解15、信息密度10、剪辑洁净10、标题摘要忠实10。必须输出各项分数，
`total_score` 等于逐项总和；Python 会重算。75 分不能通过。

内容决定与发布决定分离。阻断质量问题不能被高分抵消；风险候选可保留编辑价值，但必须明确
manual 或 blocked。重复的较弱候选保留 `duplicate_of` 审计。跨 Profile 的长短版本只记录
variant，不跨 Profile 删除。只返回 GlobalReviewOutputV4 Schema。
