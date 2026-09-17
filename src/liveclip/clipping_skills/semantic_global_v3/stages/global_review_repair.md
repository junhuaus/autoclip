# Global Review v3 repair

只修复当前 Global Review 输出的 Schema、ID、cue、计分或结构化门禁错误；不得重新执行 Discovery
或 Boundary Review。每个权威 candidate_id 恰好一条 review，score 必须等于六维和，duplicate_of
必须指向另一条已审候选。保留原始质量与风险证据，不因修复格式而升级 publish_status。只返回
GlobalReviewOutputV3 Schema。
