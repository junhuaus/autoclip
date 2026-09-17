# Global Review v3

这是候选级最终组合审查，不是全场重新扫描。只使用 candidates、各自前后局部
semantic_contexts、Discovery evidence、candidate_trace 和已经完成的 boundary_reviews。每个
Discovery candidate_id 必须恰好返回一条 reviews；风险候选和边界 drop 候选也必须保留审计行。

先远距离比较 viewer_promise、论证、示范和 payoff，给语义重复组稳定的 duplicate_group_id。
只把较弱版本标记 duplicate_weaker 并用 duplicate_of 指向保留代表；时间相邻、重叠或同一
parent_topic 不是重复依据。

content_decision 与 publish_status 分开：

- keep：Boundary Review 的最终边界可直接保留；
- repair_boundary：从给定局部上下文提出另一个真实连续、最短完整的 start/end；
- drop：内容不完整、不干净、重复较弱或无合法连续边界；
- auto：只有最终实际区间可以无需人工发布；
- manual：内容可保留，但需要普通人工审核；
- blocked：存在反义 ASR、标题改义、医学/绝对化、具体人物或地域刻板印象等阻断风险。

标题、hook、payoff 必须忠实压缩最终区间的原话立场。不得把情绪隐喻改写成身体疼痛、补充因果、
强化绝对结论，或把原片正面主张伪装成质疑/科普。ASR 可能反转原意时标
asr_meaning_reversal，不得自行静默修正文案后批准。

固定六维评分，总分必须机械相加：独立性 independence 20、完整性 completeness 20、单主题
single_topic 15、观众价值 viewer_value 20、来源忠实度 source_fidelity 15、剪辑洁净度
edit_cleanliness 10。评分针对最终建议的实际连续区间。不要围绕 75 打安全分；低质量项必须真实
拉开维度差异。top_n 只由 Python 在所有门禁之后应用，本阶段不得凑足或限制候选数。

只有 score>75、没有任何尚未修复的 quality_flag、实际时长 45--90 秒且
publish_status=auto 才能自动输出。
只返回 GlobalReviewOutputV3 Schema。
