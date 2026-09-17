# V4 bounded repair

上一次输出未通过所附 Schema 或确定性 cue/Profile/枚举校验。只修复当前 batch、边界、Chain
或候选的结构化输出；不得重做整场 Discovery 或改变未列出的对象。保留所有允许 ID、原始语义
决定和证据，只纠正明确列出的错误。只返回当前响应 Schema 的 JSON。

仅当错误为 `link relationship contradicts same-topic/objective decision` 时：
保留原始 `same_topic` 和 `same_central_objective` 两个布尔语义判断及其值，
只修改报错对象的 `relationship` 字段这一冗余关系分类，使其符合以下映射：
- 当 `same_topic=true` 且 `same_central_objective=true` 时，`relationship` 必须且只能是
  `continuation`、`supporting_example`、`next_step_same_lesson`、`summary_same_lesson` 之一。
- 当任一布尔值为 false（`same_topic=true` 且 `same_central_objective=false`、
  `same_topic=false` 且 `same_central_objective=true`、或
  `same_topic=false` 且 `same_central_objective=false`）时，`relationship` 必须且只能是
  `adjacent_but_independent`、`topic_switch`、`uncertain` 之一。
不得重新判断语义、重跑整个阶段或修改无关对象及其他字段。其他错误仍遵守上述通用修复约束。
