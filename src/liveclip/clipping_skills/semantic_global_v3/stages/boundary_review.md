# Boundary Review v3

逐个检查输入 candidates。每个 candidate_id 恰好返回一条 reviews，不能遗漏、合并或新增。
candidate_contexts 是该候选前后局部字幕，最长 180 秒；candidate_trace 给出来源 batch、窗口和
Discovery 边界报告。

检查真实开头是否承接前文、真实结尾是否讲完、内部是否夹有直播引导或设备操作、是否靠无关
内容补足最短时长、以及是否存在更短但完整的连续区间。source cue 的第一段实际话语就是开头；
不能用标题或模型概括替代。`actual_source_opening_quote` 与
`actual_source_closing_quote` 必须逐字复制建议 start/end cue 的 original_text。

- 原边界已经是最短完整连续区间：content_decision=keep。
- 找到新的合法连续区间：content_decision=repair_boundary 并返回新 start/end。
- 找不到合法干净区间：content_decision=drop；start/end 可为 null，但真实首尾引用原候选边界。

内部无关内容的 cue 写入 irrelevant_internal_cue_ids。所有 quality/risk/evidence cue 必须来自
输入。只返回 BoundaryReviewOutputV3 Schema。
