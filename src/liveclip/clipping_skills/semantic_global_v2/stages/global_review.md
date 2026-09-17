# Accuracy-first candidate scoring contract v2

逐条阅读候选原文与 linked topic。`candidate_assessments` 中每个 candidate_id 必须恰好出现一次，
并有独立六维评分；禁止抽样或用 rejection group 代替评分。

- `advance`：分数严格过线，`result_clip_id` 指向包含该 candidate_id 的 keep clip。
- `duplicate`：同一承诺由更完整的 keep clip 代表；也必须指向且被该 clip 引用，重复不等于低分。
- `reject`：`result_clip_id=null` 且有 rejected_candidates 审计；`no_general_value` 分数不得过线。

`clips` 只返回 keep。不同 viewer_promise 不得批量合并；风险只改变 clear/manual。核对 assessment
数等于 candidate_count，所有映射可反查。只返回 v2 Schema。
