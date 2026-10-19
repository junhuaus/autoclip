# LiveClip 双轨切分人工验收包

本包来自真实冷启动运行 `dual-profile-benchmark-20260924-final-cold-18`，包含 7 条短片、5 条长片，共 12 条实际渲染视频。所有视频均保留配套 SRT、画面抽帧、质量报告和审计信息。

注意：这 12 条是本次 Benchmark 命中的可评审成片，不代表系统已经自动批准发布。它们当前均为 `manual_review`，请完成人工内容、版权、健康建议和参与者声音检查后再发布。

## 推荐验收方法

1. 按下表顺序播放视频，全程佩戴耳机。
2. 同时打开同名 `.srt`，检查字幕错字、时间同步和语义。
3. 在 `人工验收清单.csv` 中填写 `通过/需调整/不采用`。
4. 重点检查开头是否能独立理解、结尾是否闭环、有无无关补时、声音是否被切断。
5. 如发现问题，记录准确的视频内时间，例如 `00:37 开始依赖上文`。

## 成片索引

| 编号 | 金标 | Profile | 时长 | 文件 | 重点检查 |
|---|---|---|---:|---|---|
| 01 | S01 | 短片 | 45.82s | `renders/short_highlight/short_highlight_0003_c01.mp4` | “第一步”开场是否仍能独立理解；“闹”字示范是否完整 |
| 02 | S02 | 短片 | 60.86s | `renders/short_highlight/short_highlight_0004_c01.mp4` | 闭口音/开口音结论是否清晰；ASR 错词是否影响理解 |
| 03 | S04 | 短片 | 54.10s | `renders/short_highlight/sh_0006_c03.mp4` | 气混与漏气的对比是否完整 |
| 04 | S05 | 短片 | 49.08s | `renders/short_highlight/sh_0007_c01.mp4` | 气混与气声差异是否完整；歌词版权风险 |
| 05 | S06 | 短片 | 50.66s | `renders/short_highlight/sh_0009_balanced_mix_step5.mp4` | 从“第五步”开始是否过度依赖前文 |
| 06 | S07 | 短片 | 72.94s | `renders/short_highlight/sh_0009_choose_sound_before_labels.mp4` | 必须听到弱混、气混及差异较小的前提；结论不能孤立 |
| 07 | S08 | 短片 | 46.80s | `renders/short_highlight/sh_0021_resing_channel_correction.mp4` | 学员样本、诊断、结论是否形成闭环 |
| 08 | L01 | 长片 | 105.00s | `renders/mini_lesson/risk_mini_0005_breathy_mix_control.mp4` | 与 S04/S05 同主题但应保留完整教学版价值 |
| 09 | L02 | 长片 | 269.64s | `renders/mini_lesson/audit_mini_lesson_0006_c03.mp4` | 必须包含第一至第四步，不能从“前三步”之后开始 |
| 10 | L03 | 长片 | 123.58s | `renders/mini_lesson/precision_mini_lesson_0007_c03.mp4` | 必须包含第五、六步和最终表达选择结论 |
| 11 | L04 | 长片 | 138.58s | `renders/mini_lesson/mini_lesson_0008_c1051_1130.mp4` | 是否存在设备/展示动作补时；结尾是否自然 |
| 12 | L05 | 长片 | 201.66s | `renders/mini_lesson/risk_mini_lesson_0016_01.mp4` | 未成年人声音、健康建议、版权及诊断边界 |

## 已知未命中项

- S03：相关内容已被发现，但最终保留的版本边界偏窄，只覆盖目标片段约 68%，没有进入这 12 条 Benchmark 命中成片。
- L07：完整范围候选已被发现，但因系统判断后续话题尚未闭环而进入 `blocked`；另一个人工审核版本只覆盖目标约 86%，因此未计为命中。

人工验收时请把这两项视为当前召回/边界问题，而不是从 12 条成片中寻找对应视频。

## 目录说明

- `renders/short_highlight/`：7 条 45–90 秒短片及字幕、质量材料。
- `renders/mini_lesson/`：5 条 90–300 秒长片及字幕、质量材料。
- `scripts/cut-scripts.md`：12 条切分脚本及原始连续字幕。
- `reports/benchmark-report.md`：Benchmark 结果。
- `reports/final-report.md`：实现、测试、性能和已知问题。
- `reports/final-validated.json`：全部候选最终状态，供深入审计。

## 技术检查现状

12 条视频均已通过完整解码、黑帧和裁切检查，分辨率为 1080×1920，编码为 H.264/AAC，实际时长与目标误差不超过 20ms。此前只验证了音轨存在和可完整解码，本次仍需要你用人耳判断音质、断句、音乐衔接和语气完整性。
