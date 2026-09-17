# Link Review v4

你只判断给定边界两侧 Fragment 是否属于同一话题、同一个中心教学目标，以及关系类型。约
180 秒字幕只是这一个边界的证据，不是完整长课的最大查看范围。可选关系：continuation、
supporting_example、next_step_same_lesson、summary_same_lesson、adjacent_but_independent、
topic_switch、uncertain。

`relationship` 必须严格遵守以下两分支映射：
- 当 `same_topic=true` 且 `same_central_objective=true` 时，`relationship` 必须且只能是
  `continuation`、`supporting_example`、`next_step_same_lesson`、`summary_same_lesson` 之一。
  这四种 linking 关系仅允许用于两个布尔值都为 true 的情况。
- 当任一布尔值为 false（`same_topic=true` 且 `same_central_objective=false`、
  `same_topic=false` 且 `same_central_objective=true`、或
  `same_topic=false` 且 `same_central_objective=false`）时，`relationship` 必须且只能是
  `adjacent_but_independent`、`topic_switch`、`uncertain` 之一。

只有 `same_topic=true` 且 `same_central_objective=true` 才能进入同一 Topic Chain。若右侧仍未
闭合，设置 `needs_next_boundary=true`；系统会继续检查下一个边界，不得因为已看过一次补看而
假设长话题结束。只返回 LinkReviewV4 Schema。
