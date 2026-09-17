# SD-1A：小课质量一致性与重复代表修复

Current outcome: SD-1A accepted and integrated,formal195929 DONE. Current Runner,
Gateway,artifact inspection and exact publication evidence are in
[the acceptance report](../verification/stable-delivery-sd1a-accepted-2026-09-12.md).
The following handoffs remain historical; do not start another SD-1A run from them.


状态：已有隔离实现，进入正式工程验证；原始启动依赖 `docs/exec-plans/liveclip-stable-delivery.md` 的 SD-0 基线确认。此任务是现有 Loop 可读取的有边界需求，不授权实现整份稳定交付路线图。


## 2026-09-12 最终基线交接（优先于历史现状）

Latest verified handoff,2026-09-12 19:59 UTC: isolated candidate
`.loop/development/sd1a-mini-artifacts-20260912/candidate`. Fresh read-only ADR040
review 01a09732-d7b3-7f60-9162-fc9b51b17f7d PASS/no findings, complete output and unchanged
b1de7b2cd10b6fcbaaa8ae09f95070556e6cf28206e8ce542461dd560a1f47aa.
313 targeted tests72aa/full lint4d00/Doctor6694 PASS. Independent b5c1 verifies
seven retained artifacts,120-second H264/AAC full decode,12 in-range SRT cues,
source/config/run identity and file hashes. Contact sheet actually viewed.
Exact three-path scope046b verifies2022unchanged paths and427original nondocument CAS.
Production/control-plane source remains identical to prior formal e2a3a790.

Seven old runs remain terminal BLOCKED with unchanged budgets/evidence. Latest
193445-7c87836e had Planner READY,Coder IMPLEMENTED/no edits,Reviewer PASS/no findings,
Tester READY and same-source Runner lint fe70/test e134 PASS (1212 Python,58 Web,
two synthetic browser flows). Gateway FAIL: mini-lesson MP4/SRT/quality artifacts
were deleted with Runner scratch. Its inspected browser ZIPs are short clips.
No original product source has been published. ADR040 corrects that concrete gap
by extending the existing125-second mock mini integration test with explicit current
contract/identity/media assertions and bounded no-follow immutable artifact retention.

New required current Runner evidence: apps/web/playwright-report/mini-lesson/<runUUID>/
manifest.json inside the exact test execution_path. Seven referenced files include
MP4,SRT,quality report/contact sheet,rough candidates,edit plans and transcript.
Correlate with the exact Runner QA/source/toolchain; verify hashes/config/current
contract and inspect actual files. Manifest is written last; missing or incomplete
artifacts cannot pass. Root is already ignored and Runner-writable; permission,
allowlist,cleanup,role and retry policies remain unchanged. Synthetic evidence only;
real semantic/media/hardware acceptance belongs to separately bounded SD-6.

This verified change permits ONE NEW bounded full SD-1A formal run; do not resume
or relabel old blocked runs. Fresh roles,required sandbox lint/test,actual artifact
inspection and Gateway are mandatory; prerequisite/historical PASS cannot substitute.
Only accepted same-source evidence plus renewed original CAS permits exact publication.
SD-1B follows accepted SD-1A. No --last,global configuration changes or budget reset.

Inherited implementation is v8/semantic-v4-quality-v2; v2–v7 and historical V4 wire/
Prompt/Schema remain frozen. ADR031–035 control prerequisites and ADR036–039 complete
repair/audit/status/indexed multipart corrections are unchanged from e2a3a790, whose
formal Reviewer and Runner passed. Q08 still requires all available Schema/domain
errors, separately indexed per business part, failure-state precedence and durable
redacted task-owned immutable audit, spent-repair preservation and successful sibling
cache. No multipart part becomes authoritative. Stage retry policy remains unchanged.

Complete2023-path baseline is prior exact assurance; three-path delta yields2025paths.
External baseline-manifest/review-input-manifest verify every unchanged byte, and
pre-formal-code-checkpoint freezes27cumulative code/config paths. HEAD differences
include inherited user work; current Coder write ownership uses trusted before/after
snapshots, not git diff HEAD. Project Python3.12/SQLite3.53.1 is required.

所有角色独立核实已有实现与Q01–Q10。若满足，Coder可如实返回 IMPLEMENTED、changed_files=[]、tests_run=[]；不制造改动，不将诊断说成本次执行。若仍有任务缺陷，唯一Coder仅在Loop分配候选根修改以下11路径，主编排已批准共享接入：

- src/liveclip/domain/semantic_validation.py
- src/liveclip/application/pipeline.py
- src/liveclip/pipeline/semantic_profiles.py
- src/liveclip/pipeline/semantic_cache.py
- src/liveclip/pipeline/stage_handlers.py
- src/liveclip/providers/llm/structured.py
- tests/unit/test_semantic_profiles.py
- tests/unit/test_semantic_validation_contract.py
- tests/unit/test_pipeline_repository.py
- tests/unit/test_semantic_global_context_budget.py
- tests/integration/test_persistent_mock_pipeline.py

STATUS/ExecPlan/ADR/交接文档由可信主编排维护，Coder只读。禁止改Make/锁/AGENTS/Loop控制面、角色权限、旧Prompt/Schema、ASR、渲染器、Web、真实data/input和旧Delivery；QA正式日志只由Runner追加。SD-1B、SD-2全阶段预算/传输、SD-3调度、付费视频验收均不属本张任务。

完整持久基线为 `/Users/junhuaxu/Workspace/AGI/liveclip-ai-v2/.loop/development/sd1a-20260912/baseline`；修正与各前置证据在原根 `.loop/development/`。使用上述11文件有界对比及局部读取，不递归diff clone/toolchain、扫描依赖目录或输出整份QA/事件/大型hash清单。证据截断按既定1MB上限拒绝，不调高上限。

必须实际新跑Planner/Coder/Reviewer/Tester/Runner/Gateway，同快照执行 required lint/test（含两类浏览器）、检查工件和完整日志，不能代用旧PASS。2plan/3code、fresh read-only assurance、Coder workspace-write/never和精确session resume不变，从不用--last。只有全部门禁通过才由可信外层发布到本独立交付根，主编排再按原dirty基线CAS精确集成。无需重问已有授权，任何角色不得修改全局配置。

## 用户结果

新小课运行不能自动交付已被模型明确判为首尾/中心目标不完整的内容；语义去重不能把一组候选互相淘汰后伪装为合法输出。模型矛盾应进入已有唯一修复路径，仍不合法则失败，并保留审计与成功兄弟缓存。

## 必读上下文与现状

先按根 AGENTS.md 阅读；再读稳定交付 ExecPlan、`docs/exec-plans/liveclip-mini-lesson-topic-chains.md`、`docs/exec-plans/liveclip-quality-gates-v3.md`。

当前 PipelineRunConfig 为 v7，mini 产物为 Schema v4。`semantic_profiles.py` 中的 `validate_boundary_review_v4` 主要校验引用、时长与连续性；`validate_profile_global_review_v4` 主要依据 flags 放行；duplicate 只检查目标 ID 存在。V3 的 `semantic_global.py` 已有 retained representative 检查，可以借鉴不变量，但不能机械覆盖 V4。

已复现反例：合法 270 秒候选的 Boundary 改成 opening_complete/ending_complete/central_objective_complete=false、contains_padding=true、opening_relevance=irrelevant、quality_flags=[]，当前仍 selected=1。两个高分候选互相 duplicate_of，均 duplicate_weaker 且具有 group ID，当前合法地 rejected=2。使用 `tests/unit/test_semantic_profiles.py` 的通用 fixture 重现；生产逻辑不得写入具体视频名称或原文。

## SD-0 启动条件

- 记录实际 HEAD、工作树与允许路径清单，不把当前未提交成果丢在新基线之外。
- 不在当前 dirty worktree 直接运行 Loop，不使用 reset/clean，不安装或改写全局权限配置。
- 主编排先明确新 validation contract、配置与缓存身份的接入方式。主编排批准共享文件变更；Coder 不越界自行修改 Schema/迁移/锁/Loop 门禁。
- 历史配置/Prompt/缓存/已交付文件原样保留。新行为必须有可区分身份，不能仅改 validator 后仍使用旧缓存身份。
- 明确分派表：冻结旧 wire loader，新 validation contract 才启用强化业务校验；新身份进入所有受影响的 Run/缓存/调用路径。增加“旧合同接受、新合同拒绝”的通用 fixture，不能直接加强旧 Pydantic loader 使历史 V4 文件不可读。

## 实现范围与文件归属

唯一 Coder 在 isolated candidate 工作，优先修改：

- `src/liveclip/pipeline/semantic_profiles.py`：结构化事实一致性、最终防御校验、重复代表完整性。
- `src/liveclip/pipeline/semantic_cache.py`：新版 validation contract 的缓存身份隔离。
- `src/liveclip/providers/llm/structured.py`：仅限完整可得 V4 验证错误送入既有唯一 repair 的最小接入；不改并发/重试调度。
- `tests/unit/test_semantic_profiles.py` 及明确命名的新版契约/缓存专项测试。

主编排独占共享接入：`src/liveclip/application/pipeline.py`、`src/liveclip/pipeline/stage_handlers.py` 的版本分派/缓存设置；若需要 Prompt/Schema 变化，先决定新的文件/版本，不修改历史冻结内容。允许路径在 coding 开始前形成最终清单；设计确需扩展时先让 Planner/主编排调整清单，不能顺便重构其他阶段。

主编排先批准共享文件的最终允许路径；必要接入由该时段唯一 Coder 在同一候选中完成，在 assurance 最终快照冻结前一起纳入。不得一边运行 Loop 一边改主交付树。若接受候选后再追加集成改动，必须对新快照重新审阅和执行正式门禁，不能沿用旧 PASS。

禁止修改：Make/锁/AGENTS/Loop 控制面和角色权限、真实 data/input、ASR、渲染器、Web、账号授权、旧 Delivery。QA 正式日志只由可信记录方追加，不由 Coder 改写。

## 必须先加的回归

| ID | 输入 | 预期 |
| --- | --- | --- |
| Q01 | 各不完整事实与空 flags，分别及组合构造 | 不得自动入选；矛盾输出被拒绝并交修复 |
| Q02 | padding/irrelevant/incomplete 枚举与“干净完整”结果矛盾 | 明确一致性错误，不静默补语义字段 |
| Q03 | 首尾、目标完整且无阻塞事实 | 正常通过，不能把全部样本一刀切拒绝 |
| Q04 | A→B→A，A→B→C→A | 拒绝重复代表环 |
| Q05 | 弱重复指向已被质量门拒绝、仍为弱重复或不存在的代表 | 拒绝；不伪造替代代表 |
| Q06 | 弱重复指向合法 retained 代表 | 在 Top-N 前验证；有效 auto/manual/blocked 及仅因 Top-N 排除的代表合法，不要求代表进入 ZIP |
| Q07 | 分数 75、76，合法时间上下限，manual/blocked | 原有阈值与发布限制不放松 |
| Q08 | 初次矛盾，以及 Schema 错误与可判定领域错误同时出现→修复成功/仍失败 | 唯一 repair 收到全部可得错误，总语义修复次数最多一次，失败不规则降级 |
| Q09 | 缓存为旧验证合同，新 Run 使用新合同 | 不作为新合同有效命中；新合同缓存可验证复用 |
| Q10 | 历史 v2–v7 配置、V3/V4 文件与 Delivery | 可读且不原地重写，不自动迁移真实案例 |

使用真实模型 Schema 验证构造最终反例，不通过不受验证的 `model_copy` 伪造“模型必然会输出”的结果；模型 mock 只在测试 profile 使用。保留完整三节点/合法代表反例，不能只针对已知两个 ID 打补丁。

## 最小实现原则

- 根据模型已经给出的布尔值、枚举、ID、风险和引用检查一致性，不根据字幕关键词判断完整性。
- 矛盾不由代码猜测哪个语义结论正确；返回结构化验证错误供原责任模型修复。
- 重复图的代表由模型给出，代码只检验引用、无环和代表最终资格；不按时间/分数自行改选代表。
- retained 定义沿用 V3：auto/manual/blocked 可以保留，但被质量、内容、分数门拒绝或本身仍弱重复的候选不能当代表。先校验代表资格，再应用 Top-N。
- 保持严格 score >75 和 auto-only 发布；Top-N 只是合法候选上限。
- 同一个无效结果不能在 Schema repair 后又获得额外 domain repair。复用完整可得验证结果的既有机制。
- 新验证版本隔离旧缓存；历史 Run 保持原合同语义，新质量合同通过显式新 generation 使用。不得清空整个缓存解决兼容问题。

## 验证与门禁

开发者现有重现命令：

```bash
.venv/bin/pytest -q tests/unit/test_semantic_profiles.py tests/unit/test_structured_repair_preflight.py tests/unit/test_settings.py
make lint
make test
```

新增契约/缓存回归须加入定向验证。以上短命令不是新 Loop allowlist；现有正式 Runner 最终只执行已配置的 lint/test，均 required。每条正式命令先追加 QA request，再追加同 ID 的 PASS/FAIL/ERROR；修复后证据绑定新快照。受权限阻塞记录 ERROR，不伪造通过。

本任务不跑付费语义或整段视频。通过这些测试只允许声明本补丁工程验证通过；产品真实内容验收留给 SD-6。

## 输出与完成标准

交付：修复及新合同接入、Q01–Q10 测试、前后复现结果、文件清单、独立 Reviewer 结论、同快照 Runner/Gateway 证据、更新的 ExecPlan/STATUS 和下一任务 SD-1B。

当 Q01/Q04 不再被错误放行、合法正例通过、缓存/历史兼容证明齐全、lint/test 通过且 P0/P1=0，才可发布本候选。首个任务完成不等于稳定交付里程碑或真实小课验收完成。

Coder 修复只 resume 明确记录的 session ID，不使用 --last。遵守现有 2 次规划/3 次编码预算；外部执行环境不支持或预算耗尽时保留证据并 blocked，不扩大权限、不隐式创建无限新 Run。

正式 Coder/Reviewer/Tester JSON 保持现有严格 Schema。审查中的文件、触发、期望/实际及测试 ID 写入允许的 evidence/fix 字符串；Coder session ID 仅由可信外层从事件/state 获取，不由模型生成。
