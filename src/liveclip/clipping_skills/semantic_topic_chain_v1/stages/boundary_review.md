# Boundary Review v4

独立检查一个候选的 Topic Chain 字幕、前后局部上下文、Discovery/Link 证据和 Profile。判断
开头独立性、结尾闭合、中心目标完整、最短完整边界、内部话题切换、无关补时和每项中断。

`keep` 必须保留输入边界；`repair_boundary` 必须返回不同的真实 cue；`drop` 可不返回边界。
若开头承接前文，先修复，不能修复则 drop。若无关内容在内部，寻找新的合法连续区间，找不到
则 drop。不得设想二次剪辑。中断按 none/minor/material 判定，未解决的 material 必须
`blocking=true`。只返回 BoundaryReviewV4 Schema。
