# Boundary Review v3 repair

只修复 validation_errors 指出的本 batch 输出，不重新评价其他 Discovery batch。保留每个权威
candidate_id，逐字复制权威首尾 cue 原文，使用存在且有序的 cue ID。每个候选恰好一条 review；
非 drop 必须有一个 45--90 秒连续区间。不要为了通过 Schema 删除质量或风险证据。只返回 Schema。
