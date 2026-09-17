# Accuracy-first candidate scoring repair v2

修复时必须保留并补齐 `candidate_assessments`：输入列出的每个 Discovery candidate_id 恰好一条，
不得删除评分账本条目来通过校验。`preserve_item_ids.candidate_assessments` 中已有条目的六项分数只在
校验错误明确指出矛盾时才可重评。

若校验指出 assessment 缺失、重复或映射错误，只修复被点名 candidate 的账本、对应 keep clip 或
rejected_candidates 引用。`advance` 必须是严格过线并指向包含该 candidate_id 的 keep clip；
`duplicate` 必须指向真正代表同一承诺的 keep clip；`reject` 必须有拒绝审计且 result_clip_id=null。
不得用一个 30-ID `no_general_value` 组替代逐候选评分。若独立六项总分已经严格过线，
`no_general_value` 不是合法修复方式：应恢复为 advance/duplicate，并同步 clip 与 coverage。
