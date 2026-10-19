# LiveClip 双 Profile 修复最终报告

日期：2026-09-24
最终真实冷启动：`dual-profile-benchmark-20260924-final-cold-18`
结论：Benchmark **PASS 90.36**，并完成 12 条真实 FFmpeg 剪辑与画面检查。

## 1. 根因

旧 v12/v13 链路以单个 `clip_profile` 驱动互斥分支，因此一次运行只会进入短片或历史
mini 路径。当前短片运行中的 `mini_lesson` 只是“请求/期望”，没有独立进入 Discovery。

逐链路结论：

1. 旧请求/API 只有标量 Profile；新入口明确请求两个 Profile。
2. 旧运行中 mini 没有进入短片 Discovery；新实现直接执行独立 600/300 长片扫描。
3. 旧标量时长配置把有效上限固定在 90 秒；新配置按 Profile 校验，90 秒整归短片，
   长片严格大于 90 秒且不超过 300 秒。
4. 旧 Prompt/执行分支只覆盖当前标量 Profile；新 Prompt 和评价目标按 Profile 装载。
5. 旧候选 Schema/validator 随单 Profile 使用短片上限；新 Schema/validator 按候选
   `profile` 校验。
6. 旧单池语义去重可能让包含短版的长版没有独立生存空间；新实现只允许同 Profile
   去重，跨 Profile 禁止去重。
7. 旧 Top-N 作用于一个 Profile 的单池；新实现按 Profile 分别评分和 Top-N。
8. 旧 assembler/manifest 只描述当前标量 Profile；新 final 同时序列化两个 Profile。
9. FFmpeg 本身可处理 90--300 秒；旧链路从未把长片送到渲染器。真实测试已渲染
   105--269.64 秒长片。
10. 新缓存键包含 source、Profile、窗口、Prompt hash、模型/设置、Schema/算法、
    output model 和实际 payload hash；manifest 分开记录 requested/executed，统计由最终
    数组重算。

## 2. 修改文件

- 核心：`src/liveclip/pipeline/dual_profile.py`、
  `src/liveclip/services/dual_profile_evaluation.py`、`src/liveclip/cli/app.py`。
- Provider/进程：`src/liveclip/providers/llm/structured.py`、
  `src/liveclip/media/process.py`。
- Prompt：`src/liveclip/clipping_skills/dual_profile_v1/` 下的 Profile 与九个阶段文件。
- 工具：`scripts/evaluate_benchmark.py`、`scripts/export_dual_profile_scripts.py`。
- 测试：`tests/unit/test_dual_profile.py`、`tests/unit/test_benchmark_evaluator.py`、
  `tests/unit/test_dual_profile_render.py`、`tests/unit/test_media_process.py`、
  `tests/integration/test_dual_profile_evaluation.py`。
- 计划/状态：`docs/exec-plans/liveclip-dual-profile-benchmark-v1.md`、`STATUS.md`。

## 3. 短片 Discovery 改动

保留 120 秒逻辑窗口、60 秒步长、边界状态和必要的补看；增加 ownership coverage
audit，候选只能由其开始时间所属的半开区间输出。短片保留独立候选池、边界复核、
Global Review、Global Audit、Top-N 与终态统计。

## 4. 长片 Discovery 改动

新增直接读取完整字幕的 600 秒窗口、300 秒步长、半开 ownership interval 和尾部窗口。
长片直接寻找完整教学、案例、多步骤方法与诊断纠正闭环，不读取短片结果，也不机械拼接。
另有 coverage、precision、confirmation 和 risk discovery，用于召回完整单元与风险链。

## 5. 双 Profile Schema 和配置

`short_highlight` 为 `[45000, 90000]` ms；`mini_lesson` 为 `(90000, 300000]` ms。
每条最终候选携带 Profile、variant group、source candidate/window lineage、cue/time、
review status、quality flags 和 risk tags。

## 6. 去重、Top-N、validator 与 assembler

Agent 只在同 Profile 内做语义去重；Python 不用关键词、标点、时间包含或重叠率推断重复。
跨 Profile 只运行 Variant Link，不能评分、改边界、拒绝或去重。Python 只执行 Schema、
cue/time 真实性、连续单区间、Profile 时长、分数/风险门控、Profile-local Top-N 和统计守恒。

## 7. 缓存与 manifest

最终冷启动 `cache_hits=0`。requested/executed 均为
`[short_highlight, mini_lesson]`。最终守恒：短片 raw/final 87/87，长片 raw/final 105/105；
每个 final candidate ID 唯一，manifest 统计与最终数组一致。

## 8. 新增测试

覆盖双 Profile 实际执行、90 秒边界、全局短片上限不覆盖长片、长窗口召回、短长变体共存、
同 Profile 去重/跨 Profile 禁止去重、独立评分和 Top-N、禁止 CTA/设备补时、RGR-02、
S07 前提、L01--L03、风险路由、raw/final 守恒、Profile/payload 缓存键、mock LLM、
真实渲染子集和渲染 CLI 绝对 forbidden-root 回归。

## 9. 测试命令和结果

- `make lint`：PASS（Ruff、format、mypy、Schema、TypeScript）。
- 定向测试：33/33 PASS。
- `PATH=/opt/homebrew/bin:$PATH make test`：2495 PASS、1 FAIL、15 warnings，21m43s。
- 唯一失败为既有 loop-engineering toolchain snapshot：macOS 临时 secure-cache 目录原子
  rename 返回 `PermissionError`，与双 Profile 产品链路无关；未把完整测试描述为全绿。
- 未带 Homebrew PATH 的首次测试因找不到 FFmpeg 产生系统性失败；单例复现后使用正确
  PATH 重跑，媒体相关失败全部消失。

## 10. Benchmark 分数

PASS，90.36；硬失败 0；自动通过中的硬质量错误 0。

## 11. 短片命中

7/8：S01、S02、S04、S05、S06、S07、S08。

## 12. 长片命中

5/6：L01、L02、L03、L04、L05。

## 13. L01、L02、L03

- L01：`risk_mini_0005_breathy_mix_control`，00:27:17.560--00:29:02.560，
  105.000 秒，manual review，88 分。
- L02：`audit_mini_lesson_0006_c03`，00:31:30.420--00:36:00.060，
  269.640 秒，manual review，86 分。
- L03：`precision_mini_lesson_0007_c03`，00:36:00.060--00:38:03.640，
  123.580 秒，manual review，90 分。

## 14. RGR-02

`sh_0008_c02` 覆盖 00:34:30.980--00:36:00.060，为 blocked、34 分，带
`missing_required_prior_steps` 和 `asr_uncertain_blocks_meaning`，没有自动通过。

## 15. S07 边界

`sh_0009_choose_sound_before_labels` 为 00:36:50.700--00:38:03.640，72.940 秒，
manual review、89 分；从弱混/气混与表达选择前提开始，不再从 00:37:17 附近的结论开始。

## 16. 风险锚点

- R01：`risk_mini_0013_two_vocal_faults_first_diagnosis`，blocked，完整风险链保留。
- R02：`mini_lesson_0014_c02`，manual review。
- 风险内容在 Discovery 可见，未被提前隐藏；医学、健康、绝对化、敏感性、参与者音频、
  未成年人隐私、版权和 ASR 风险按证据累计。

## 17. raw/final 一致性

短片 87 个 raw 全部进入 48 manual、21 blocked、18 rejected；长片 105 个 raw 全部进入
33 manual、32 blocked、40 rejected。两者 selected 均为 0；本次 Benchmark 命中均因风险
标签进入 manual/blocked，未绕过门控制造自动选择。

## 18. 模型、Prompt hash、token、调用次数和耗时

- Provider/model：`codex_cli` / `gpt-5.6-sol`。
- 输入/输出 token：6,645,600 / 626,578。
- 调用：Discovery 159、Boundary 49、Global Review/Audit 19、Variant Link 1；缓存命中 0，
  repair 4，retry 0。
- 墙钟约 4,409 秒；并发累计 provider latency 13,321,917 ms。
- Prompt hashes：
  - short discovery `560083a53e4a04c9d8917c7efeed32849269141ece13df60a522e83ba0d3ef07`
  - short coverage `5cf38c6d0cff076721437ecb88e64c3b37b7e942af9d7c7756d8c71220b2727d`
  - short boundary `26f5f09f778011821d1cc53c66c17c7f1b2a73b57f457be14a78de011b338a91`
  - short review `be7023a5007684edd947f66f4bd9e5f46a568183dbb331e7eb23f1c16878f627`
  - short audit `fd7f1b2d488f9712151563b831cdb0c2e7ef6e8eadd8d1b71c0f1aafe4e7a0fb`
  - mini discovery `bd807b720db282447efc180dfec11f1aa2d94a173d8e4de2bb78b82cbc83b885`
  - mini coverage `057f0a5bb3a3bdeb24c08dc44cd3f78e6c148742390475c226da4f3fcff091f3`
  - mini precision `ef399dc6090a7f108a07cee47f858ab28d61b7f00e2d048583ca6cf05d8ec443`
  - mini confirmation `3ccb77bc963fa0e906207c33a55297dc1245021e8c6e47ad26e1ee4e1a82c5aa`
  - mini risk `f136669d1b7560711c74e31b3ed3326cfab6c5df9e0c462d8acca5c12b03f3f9`
  - mini boundary `d832575dc52b8a5a6071ec005888738a064fecdcfc37fdd2191b798175352c70`
  - mini review `c8cc89e9793a340a64ba868570efa665b7c71d1268438cefee21995dcb1f605b`
  - mini audit `ee8b32b1cf58eb9604dd14b6d6821b202cb5ecf1f0924ec51300d961c17adbdc`
  - variant link `def25b05bd987a293cf74d5f964ca00504d8d247cfd8b1d4af17299289152aef`

## 19. FFmpeg 输出

真实源 `input/8-30.ts` 已渲染全部 12 个 Benchmark 命中：7 个短片、5 个长片，总时长
1,218.720 秒，总视频大小 1,056,261,573 bytes。编码器为 `h264_videotoolbox`，全部一次成功。
每条均有 MP4、SRT、SHA-256、质量 JSON、三帧和 contact sheet；1080x1920、H.264/AAC，
ffprobe 时长差 0--20 ms，full decode/black frame/crop 检查通过，人工画面检查 12/12
`viewed_passed`。

## 20. 尚未解决的问题

1. 严格的 110 分钟全新素材冷启动仍慢：本次约 73 分 29 秒；主要瓶颈是模型语义分析，
   不是 FFmpeg。12 条实际编码约 3 分 20 秒。相同素材/Prompt 可由缓存显著加速，新的长素材
   若继续使用完整 Benchmark 深度仍应预期接近一小时。
2. 未进行人耳音频内容/音质试听；仅验证音轨存在、完整解码与画面质量。
3. 完整测试仍有一个与本功能无关的 loop-engineering 临时目录权限失败，见第 9 节。
