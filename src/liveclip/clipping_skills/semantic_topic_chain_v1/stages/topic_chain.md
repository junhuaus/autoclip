# Topic Chain Review v4

输入是 Python 仅按已确认 Link Review 组成的一个 Topic Chain，以及该 Chain 的完整连续字幕。
确认中心问题、学习结果、教学提纲和左右闭合状态，并为请求的 Profile 输出最短完整候选。

若 Chain 超过 300 秒，判断是否存在自然教学子单元。每个输出子单元必须有独立问题、解释和
结论，并提供自然分割证据；没有自然分割时不输出候选，使用
`topic_too_long_without_natural_split`。不得每 300 秒机械切割或截断半句话、半个步骤、缺少
结论。只返回 TopicChainReviewV4 Schema。
