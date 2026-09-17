# High-recall Discovery v2 delta

Discovery 是高召回目录，不执行 75 分门槛，不读取或服从 top_n，不因预期 manual/blocked 风险
减少候选。直播插话或设备中断位于候选内部时仍召回有价值话题，并在 boundary_notes 与
evidence_cue_ids 中明确实际 cue，交给独立 Boundary Review 寻找干净连续边界或删除。Discovery
不得把风险、边界瑕疵或最终数量上限当成 no_candidate 理由。
