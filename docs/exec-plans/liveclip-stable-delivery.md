# LiveClip 稳定交付 Living ExecPlan

状态：SD-0至SD-3已正式工程验收并集成；当前推进SD-4，真实验收及后续路线图仍未完成。

本计划遵循 `.agent/PLANS.md`，承接 `docs/PRODUCT_SPEC.md`、`docs/SOLUTION.md` 及既有 v1/v0.2 计划。它是一次稳定性里程碑，不把项目改名为标书系统，不宣布软件版本已升级，也不重写已交付历史。用户已再次明确授权持续执行至开发完成；按以下依赖顺序逐个实施有边界工作包。SD-0/SD-1A/SD-1B/SD-2 已通过正式门禁；继续实施 SD-3 及后续路线图；每个 Coder 任务书的文件、权限和预算边界保持。

## 1. Purpose / Big Picture

用户给出一个授权本地视频，使用一个高层命令，能够：

1. 获得语义完整、来源可信、满足所选 Profile 的切片。
2. 默认选择并生成可浏览 MP4/SRT/manifest/ZIP，也可保留手工选择。
3. 全程知道当前动作、实际进展、耗时及失败原因。
4. 中断后继续原任务，复用已验证成果，不重新创建项目或重复生成交付版本。
5. 不需要 Codex 开发会话参与视频处理；产品运行时自己完成实际模型调用及媒体处理。

本里程碑的成功标准是“可靠完成用户任务”，不是增加 Agent 数量、扩展框架或强制输出 15 个片段。短高光保持 45/60/90 秒，小课保持 90/180/300 秒；严格分数门和 Top-N 上限不因性能优化而放松。ASR 准确性、源文件只读、原视频内嵌文字保留、干净成片与独立 SRT 的既有产品约束不变。

## 2. Context and Orientation

仓库：`/Users/junhuaxu/Workspace/AGI/liveclip-ai-v2`；分支：`liveclip-v2/loop-engineering`；规划时 HEAD：`6009b23`。开始任何开发必须重新核对，不能把这个提交当作当前全部实现。

规划时有 59 个 tracked 修改文件，另有未跟踪的代码、Prompt、Schema、测试、控制面和研究产物。当前可运行成果大部分尚未进入 HEAD。禁止 reset、清理未跟踪文件、覆盖用户修改，禁止把“直接从 HEAD clone”误认为完整基线。

核心路径：

| 层 | 当前位置与职责 |
| --- | --- |
| 入口 | `src/liveclip/cli/app.py`、`src/liveclip/api/`、`apps/web/src/` |
| 应用服务 | `src/liveclip/application/`；Pipeline、Selection、Delivery、权限与查询 |
| 持久化 | `src/liveclip/db/`；SQLite、任务租约、状态与幂等 |
| 语义流程 | `src/liveclip/pipeline/stage_handlers.py`、`semantic_global.py`、`semantic_profiles.py` |
| 模型适配 | `src/liveclip/providers/asr/`、`providers/llm/structured.py`、`providers/readiness.py` |
| 版本契约 | `src/liveclip/clipping_skills/`、`src/liveclip/schemas/`、PipelineRunConfig |
| 媒体与交付 | `src/liveclip/media/`、`renderer/`、`delivery/`及应用服务 |
| 开发控制面 | `tools/loop_engineering/`、`config/loop-engineering/`、`loop-engineering.yaml` |

规划依据与已知差距：

- 规划时 Pipeline 配置为 v7；SD-1A 已按 ADR030 采用并集成 v8，新旧合同分派经过正式门禁；SD-1B 已集成小课 V9 配置与 Schema v5 来源账本，其他算法保留 V8。软件版本、Pipeline 配置版本、Prompt 版本、Schema 版本是不同概念。
- 已复现：Boundary 明示首尾或目标不完整，却因 `quality_flags=[]` 自动通过。
- 已复现：两个候选互相 `duplicate_of`，整体被淘汰且输出仍被接受。
- 已复现：10 个 270 秒候选、每秒一个 cue 的合成 payload 约 145k tokens，超过默认 74,240 的预算。它不是实际视频耗时或质量证据。
- 当前 `auto` 的交付意图只在 CLI 参数中；`retry --wait` 不恢复选择与打包。
- 当前打包等待没有完整 TUI 刷新，watch 会在六阶段 completed 时提前退出。
- 当前入口默认配置分散；Web 尚无小课选择控件。
- 最近成功运行 `5721db5f88ff455cbf45c56f2a6bda65` 是历史 config v5 / Global Review v2：六阶段约 93 分 40 秒，其中 MLX ASR 35 分 27 秒、编辑 39 分 17 秒。62 条 Codex 记录中 27 条 invalid。它不能证明新 V3/V4 已验收。
- 小课真实运行 `30eba26459e34b8187fa15900670c78a` 已成功 ASR 78 次，但 28 次 Discovery 本地启动因嵌套执行限制失败，没有真实小课成片。证据：`data/evaluations/8-30-mini-lesson-topic-chain-2026-09-11/before-after-report.md`。
- 前一轮只读审计的四组测试为 39 passed；仓库历史记录的 1006 Python tests 不等于本计划完成后的测试证据。

## 3. Scope 与明确非目标

本轮包含：质量一致性、重复代表、请求预算、候选来源闭合、受限并发与失败恢复、持久化交付目标、统一预设、完整进度、真实验收、运行文档。

本轮不包含：新增云服务、微服务、Redis/消息队列、通用 DAG 框架、换 ASR 模型、无证据改模型默认值、新平台自动发布、字幕擦除/背景恢复、扩展团队协作功能、重写全部代码、改造 Loop 为并发自治平台。

保留兼容：历史 A/B/Full-first、已有账号和授权、单次干净母版渲染、不可变 Delivery、旧项目及缓存可读。旧实验能力不删除，标明适用范围即可。已有风险门不通过的内容仍为 audit-only，不能被默认选择重新放行。

## 4. 两个控制平面与 Agent 结构

### 4.1 开发阶段，不属于产品运行时

```text
DevelopmentOrchestrator（当前主开发编排器）
├─ Planner：任务拆解、契约与依赖，fresh / read-only
├─ Coder：唯一写入者，isolated candidate，明确 session ID
├─ Reviewer：独立代码与产品审查，fresh / read-only
├─ Tester：测试设计与证据分析，fresh / read-only
├─ Gateway：独立最终判断，fresh / read-only
└─ DeterministicRunner：非 AI；执行 allowlist、记录证据、验证快照
```

五个角色复用 `loop-engineering.yaml` 的现有角色与 `config/loop-engineering/profiles/`，不在准备阶段更换模型或新建十套 Agent 服务。主编排器负责范围、共享文件、集成与最终证据判断；没有单独的“AI Controller”混入产品。

外层可以临时分配三个只读 specialist：

| Specialist | 责任 | 必须输出 |
| --- | --- | --- |
| semantic-quality-reviewer | 原文证据、边界、链、重复、风险、token 预算 | 可复现反例、受影响函数、正/反测试 |
| workflow-contract-reviewer | 恢复、幂等、权限、状态、入口兼容 | 状态表、事务边界、迁移与故障矩阵 |
| qa-performance-reviewer | 验收、耗时、真实模型证据、回归、发布 | 测试 ID、命令 ID、测量口径、阻塞 |

这些是开发只读任务，不新增 Loop 配置角色，也不是 RuntimeBusinessAgent。它们的摘要供 Planner/Reviewer 使用，不能替代正式 Reviewer、Runner 或 Gateway 回执。

### 4.2 四个并发槽如何使用

| 阶段 | 槽 1 | 槽 2 | 槽 3 | 槽 4 |
| --- | --- | --- | --- | --- |
| 设计/审计 | 主编排 | 语义审计 | 工作流审计 | QA/性能审计 |
| 编码辅助 | 主编排 | 唯一 Coder | 下一任务测试设计（只读） | 不重叠问题分析（只读） |
| 冻结后审查 | 主编排 | 语义/安全审阅 | 恢复/兼容审阅 | QA 证据分析 |

现有 Loop 内部仍按 `planning → coding → reviewing → test_planning → running → final_gate` 串行执行，且子角色禁用 multi-agent；上表是外层调度，不是宣称 Loop 已实现并行流水线。编码期的只读观察不算最终审查，最终审查必须面对冻结的同一候选快照。

默认始终只有一个产品代码写者。无需为了并行而开发 worktree 管理器。主编排器拥有 Schema、迁移、锁文件、共享 DTO、bootstrap、Solution/ADR、ExecPlan、STATUS 和集成修改；若它需要编码，也必须作为该时段的唯一 Coder 在候选环境中工作。

### 4.3 产品运行时，继续用现有实现

```text
CLI / API / Web → 共享应用服务 → 六阶段 Pipeline / durable Task
  ASR → Discovery → [mini: Link → Topic Chain]
      → Boundary Review → Global Review → 确定性质量门 → FFmpeg
      → Selection → Delivery
```

这些语义角色由 `structured.py` 和版本化 Prompt 调用真实模型，不由开发 subagent 代跑。新引入的交付协调只串接已有动作，不理解字幕、不修改模型结论、不成为通用 Agent Runtime。

## 5. 工作包契约：适合小步 vibecoding

每个 Coding Session 只处理一个有边界的任务；通常 2–6 个实现/测试文件，超过时按契约与实现拆包，不以机械行数限制牺牲必要修复。不要一次把本计划所有阶段交给一个 Coder。

任务输入必须包含：`task_id`、用户结果、基线 HEAD/工作树指纹、前置依赖、允许文件、禁止文件、权威文档、已知反例、验收条件、命令 ID、兼容策略、预算和退出条件。

执行顺序：读上下文 → 最小设计 → 先证明失败测试 → 最小实现 → 定向回归 → 冻结快照 → 独立审阅 → Runner → Gateway → 外层发布 → 更新交接。

正式角色 JSON 必须遵守现有 `config/loop-engineering/schemas/`，不得为了本计划添加未允许字段。Coder 使用 `verdict/summary/changed_files/tests_run/remaining`；精确 session ID 由可信外层从进程事件与 state 读取，不接受模型自报。Reviewer 每项仅使用 `severity/summary/evidence/fix`，将文件/行号、触发条件、期望/实际写入 evidence，将修复要求与测试 ID 写入 fix。Tester 只能申请已登记命令 ID。模型输出不得变成可执行 shell。

未通过质量门的候选不能发布。当前 Loop 使用最多 2 个 plan cycles、3 个 code cycles；不另加隐藏重试。预算耗尽或环境错误写明 blocked；重新建 Loop Run 必须带前次原因，不能借新 ID 无限重试。

## 6. 架构契约：先冻结，再编码

### A. 语义验证与缓存身份

- 为新的验证行为、传输格式分别建立可追溯 contract identity；仅改 Python validator 不会改变现有 output Schema hash，不能继续误命中旧缓存。
- 主编排器在 SD-0/SD-1 决定是否新增 Pipeline 配置版本及字段，写 ADR 后实施。历史 v2–v7 不原地改指纹；旧 Prompt、Schema、缓存和 Delivery 不覆盖。
- 新运行用新合同；旧运行读取继续兼容。显式将旧任务提升为新版质量合同应新建 generation，不能假装同一旧 Run 原样重试。
- 历史交付仍可读；迁移不得自动重新选片、重新付费或批量处理真实案例。
- SD-0 必须给出旧 wire loader / 新业务 validator / Run contract / cache key 的明确分派表。冻结旧 wire loader，不直接增强同名 Pydantic 校验导致旧文件无法读取；用“旧合同接受、新合同拒绝”的 fixture 验证分派。新身份进入所有受影响语义缓存键。

### B. 薄交付意图与应用服务（提议，尚未实现）

新增 `RunCompletionIntent`，与不可变 PipelineRunConfig 分离，绑定确切 `project_id/run_id/generation/requester_id`。记录 `target=process_only|delivery`、`selection_policy=default|manual`、ZIP 选项、preset 版本、幂等动作键、selection checkpoint、delivery_id、乐观锁版本及取消意图。

`CompletionService` 只驱动：处理完成 → 选择策略 → 现有 DeliveryService → 等待绑定的 Delivery；不复制原有六阶段状态机。状态由绑定资源和动作 checkpoint 共同推导，不按 `Project.current_run_id` 无条件漂移。

交付推进必须有持久化调度入口，复用既有 Task/lease 机制进行固定动作的幂等 reconcile，不能只在 CLI 的内存循环中调用。客户端断开后 Worker 仍可推进，进程重启后从意图和绑定动作恢复；具体 Task kind/迁移在 SD-4 冻结，不新增外部调度基础设施。

| 查询字段 | 提议值 |
| --- | --- |
| phase | processing / waiting_selection / packaging / terminal |
| status | active / needs_action / succeeded / failed / cancelled |
| outcome | processed / delivered / no_eligible_clips / no_selected_clips；未终结为空 |

不再把 Pipeline 100% 当作交付完成。旧 Run 没有 intent 时按 process_only 解释；只有新的明确交付操作才创建交付意图。`resume` 是本计划拟新增命令，当前不能使用。

manual 模式的“提交选择”必须明确绑定 generation 与候选 revision 集；selected_count=0 不表示用户已提交空选择。只有显式提交空集合才得到 no_selected_clips。集合随后变化需重新确认。多个未完成意图有歧义时要求明确 intent，不猜测需要恢复哪个任务。

### C. 预设与进度（提议，尚未实现）

应用层集中解析版本化 preset；领域 profile 与 clip profile 正交。短高光/小课一次选定算法及对应时长，启动前展示配置摘要。新入口可使用推荐 preset，历史 API 请求形态保留旧默认，弃用路径单独说明。

`CompletionSnapshot` 为 CLI/API/Web 共用只读视图：阶段、动作、计数、缓存、修复、当前调用耗时、业务进展时间、heartbeat/lease、Delivery 文件/字节进度和可执行下一步。无总量时显示活动与耗时，不伪造 ETA。watch 不执行任务或恢复任务。

## 7. Milestones 与依赖顺序

```text
SD-0 基线/契约/测试准备
  → SD-1 语义质量门与候选来源
  → SD-2 请求预算与上下文去重
  → SD-3 Provider 预检/并发/重试与缓存
  → SD-4 持久化交付目标与恢复
  → SD-5 统一预设/完整 TUI/Web
  → SD-6 真实语义、成品与性能验收
  → SD-7 发布收口
```

SD-4/SD-5 的只读设计、验收用例可提前并行。修改 `stage_handlers.py`、`pipeline.py`、CLI 等共享文件的任务串行集成。每个阶段都要给出用户可观察证据，不在阶段完成后统一补测试。

里程碑进度：

- [x] SD-0：受保护基线与首任务契约就绪。
- [x] 2026-09-12 PDT SD-1A：formal195929 DONE，Reviewer/Gateway PASS；当前Runner1212Python/58Web/两类浏览器和120秒小课工件验收通过；27代码/配置路径与21支持文档已通过CAS集成。
- [x] 2026-09-13 SD-1B：formal072557 DONE；1818Python/58Web/两浏览器、V8/V9工件/SQLite/ZIP及Gateway通过；33实际路径CAS集成，28问题闭合。
- [x] 2026-09-13 SD-2：formal4aa6346f DONE；1934Python/58Web/两浏览器、三配置小课与当前工件通过；16路径CAS集成，六问题闭合。
- [x] 2026-09-13 SD-3：formal20260913T180522Z-532b2b05 DONE；当前门禁、四配置小课、恢复SQLite与浏览器工件通过，33路径CAS集成。
- [x] 2026-09-14 SD-4：formal20260914T052758Z-fb55229f DONE；持久化目标、恢复与幂等交付通过合成工程验收，47路径CAS发布。
- [ ] SD-5：入口预设与完整 TUI/Web。
- [ ] SD-6：真实模型、成品、长输入及性能验收。
- [ ] SD-7：可重建检查点与运维文档。

### SD-0：基线与开工条件

- [x] 2026-09-11：完成三项只读专项规划并建立本计划、首个任务书。
- [x] 重新盘点 dirty worktree，区分用户改动、代码/测试、系统契约、案例输出；保留全部原件。
- [x] 审核“原有 tracked 文件＋明确批准的新代码/配置/文档/测试”路径清单；源视频、数据库、凭据、普通 data 输出不纳入开发快照。
- [x] 在允许的目录建立完整独立 clone/专用基线，转入已核对改动并验证哈希；不能只 clone HEAD 丢掉未提交成果。未授权目录不写入。
- [x] 核对 Loop 输入与 assurance 快照一致性：当前未忽略 data/evaluations 被 fingerprint 纳入却被 toolchain 排除，存在失配风险。通过限定基线解决，不让 Coder 绕过指纹检查。
- [x] 不使用尚未支持的普通 git worktree 作为 Loop 根：当前 toolchain 将 `.git` 当目录复制；先使用完整 clone，不为本轮扩建 worktree 功能。
- [x] 主编排已按 ADR030 冻结 SD-1A 必需的 validation/cache 身份、兼容与测试门决策；transport 和 CompletionIntent 在各自工作包前冻结，不用远期设计阻塞首个修复。若需变更 Make/锁/Loop allowlist，先独立审查并形成新基线，再启动产品 Coder；不能运行中修改门禁。
- [x] 已记录本地基线测试和普通主机 Loop Doctor/门禁能力（下方按快照列明）。不得自动安装全局 profiles、推送远端、付费运行或改变权限。

交付：基线路径/指纹/文件清单、契约决策、可执行首个任务。Loop 当前未完成的普通主机验收如受环境阻塞，标明范围；不通过关掉 sandbox 来“修复”。

### SD-1：语义正确性与来源闭合

**SD-1A（第一张开发任务）**：修复 Boundary 事实/flags 矛盾、重复代表循环/失效，以及新验证合同的缓存身份。

文件：`pipeline/semantic_profiles.py`、`pipeline/semantic_cache.py`；必要配置/调用接入由主编排独占 `application/pipeline.py`、`pipeline/stage_handlers.py`，包括 `providers/llm/structured.py` 中将完整可得 V4 错误送入唯一 repair 的最小接入；测试为语义 Profile、修复、缓存及配置契约测试。队列/并发改造仍留给 SD-3。

先加反例：不完整首尾/目标、padding/irrelevant 与空 flags；A→B→A、三节点环、被拒绝代表、合法保留代表；严格阈值 75；新旧验证缓存隔离。错误必须送唯一一次领域/结构修复，不能静默补 flags。

retained 代表沿用 V3 的边界：可以是有效 auto、manual、blocked 或仅被 Top-N 排除的合格候选；不能因质量/内容/分数被拒绝，也不能本身仍是弱重复。代表验证在 Top-N 截断前完成，不错误要求每个代表进入 ZIP。

**SD-1B**：为 Discovery→Chain→自然子单元→最终 disposition 建立完整一对多映射，携带带来源的风险。修改新版 Prompt/Schema，不覆盖 `semantic_topic_chain_v1`。每个原候选必须有终态，合法零候选、手动、阻塞和 Top-N 排除不是缺记录。

验收：已复现两个漏洞被测试阻止，合法样本继续通过；候选去向 100% 闭合；无关键词语义规则，无规则 fallback；历史交付未改。

### SD-2：上下文与 token 预算

优先新增小型纯转换模块 `pipeline/semantic_transport.py`，统一 cue 表、引用与预算；`semantic_profiles.py` 构造 payload，`structured.py` 为 object/compact/repair 使用相同解码路径。调用边界必须计量实际序列化后的 Prompt、payload、Schema/输出预留及安全边界。

SD-2A：重复字幕只传一次；只缩减合同允许的附加背景，不删实际候选、必要 Chain、修复后边界或证据。SD-2B：所有语义阶段加入调用前预算门，包括超长 Chain 和 repair 请求。

验收：145k 合成样本压入预算，或在零模型调用下返回明确预算错误；两种表示重建结果一致；repair 保留全部权威 ID。先不引入新评分层级；压缩仍不够时另作有证据的架构决策。

### SD-3：失败预检、有限队列与及时缓存

文件：`providers/readiness.py`、`providers/llm/structured.py`、`pipeline/stage_handlers.py`，共享 bootstrap 和错误 DTO 由主编排集成。

- 新全流程在付费 ASR 前检查将要使用的能力；本地版本/登录检测不冒充实际推理 smoke。可确定的嵌套/权限限制应提前报出，不清除限制来强行执行。
- 恢复时根据剩余动作检查依赖：只剩 render/package 不要求无关 ASR/模型凭据。
- 全量 submit 改为有限 in-flight 队列；全局永久错误停止未启动任务，保留已完成兄弟任务缓存。
- 每单元包含生成、完整可得校验、唯一修复；慢 repair 不堵塞其他结果的记录与进度。
- 网络瞬态退避、请求修复、阶段恢复分别计数；同一确定性无效输出不能靠整阶段自动重跑无限增加修复预算。改变配置的重跑必须显式建立新身份。

验收：28 个待执行任务遇首个永久错误时，不再全量启动；启动数有并发上界；缓存成功数及时可见。覆盖取消、租约失效、部分成功、中途异常、修复失败与重复恢复。

### SD-4：恢复原交付任务

主编排管理一张薄意图表的迁移、共享 DTO/ports；唯一后端 Coder 实现建议的新 `application/completion.py`、对应 repository、Selection 幂等透传和 Delivery 协调。复用现有 `DeliveryService.enqueue(IdempotencyContext)` 和 Review batch 的事务能力。

必测故障点：六阶段前后；选择提交后但响应未返回；Delivery enqueue 后但 ID 未记录；文件发布前后；并发 resume；新 generation；人工排除/全部排除；修订造成 stale master；权限撤销。

补充无客户端场景：API 发起自动任务后客户端断开；六阶段完成时 CLI 已不在场；Worker 在选择/打包协调前后重启，均能由持久化任务继续。区分“退出观察”与用户显式取消；manual 未提交不能被当成空选择完成。

验收：恢复不新建 Project，不重复有有效缓存的模型任务，不重新覆盖人工排除，不多造 Delivery 版本；manual 模式等待选择；零合格和零选择各有明确 outcome，不生成伪空包。旧 Run 默认仍只处理。

### SD-5：统一入口与完整 Text UI

主编排冻结 preset/API DTO/TS 类型；CLI 的目标恢复、预设和 TUI 修改由同一 owner 串行完成；Web owner 只修改组件、请求构造及其测试。

高层拟提供 `auto VIDEO` 与 `resume PROJECT_ID`，既有低层 `run/retry/stage/select/package` 保留。CLI/API/Web 的推荐 preset 解析为相同业务配置；Web 可选短高光/小课。旧接口默认值不静默切换。

TUI 覆盖 processing、selection、render、copy/hash/ZIP；watch 在 packaging 时持续显示。刷新目标约 2 秒，标明业务进展与心跳的差别；显示动态工作总量，不用六阶段权重假装准确 ETA。

验收：窄终端、中文长行、resize、非 TTY、长异常不持续滚屏；watch Ctrl-C 只退出观察；执行端取消尊重租约和原子发布；成功展示绝对包路径；无包时不输出假的成功路径。

### SD-6：真实模型、媒体与性能

先通过离线工程 gate，再使用合法生产凭据和受支持普通主机环境。真实模型测试与 Loop Runner 分离：Runner 当前仅允许 localhost 并清理云凭据，不在其 sandbox 内偷开外网或嵌套开发会话。

SD-6A：同一冻结 transcript、同一模型及参数，对每个待发布 Profile 至少 3 次独立真实语义运行；禁用语义缓存用于稳定性测量，并与故障恢复缓存测试明确区分。冻结人工参考标签后再看输出，不调规则去凑片数。

SD-6B：每个待发布 Profile 至少一次完整输入→ASR→真实语义→MP4/SRT→Delivery，以及一次注入故障后的恢复；另选不同来源验证泛化。旧小课 Run 只能证明其历史合同的恢复；新合同验收用新 generation/Run，仅在合法身份相同时复用 ASR。

SD-6C：2 小时/4 小时代表输入分别测冷运行和恢复；视频只读。统计各阶段 wall time、排队/模型/修复/缓存、token/费用、峰值内存、磁盘和交付耗时。没有足够长输入或许可时明确留下验收阻塞，不用短片外推。

内容验收：人工查看并听取每个自动交付片段，核对开头/结尾、中心目标、误拼接、含义、风险与源时间；图片 contact sheet 不能替代音频/语义检查。全部 MP4 full decode、流格式、时长、SRT 时间轴、ZIP/manifest 校验通过。

建议在 SD-0 冻结的量化目标：自动片段边界完整率 ≥95%，人工保留率 ≥90%，标注可切主题召回率 ≥90%，严重含义/风险漏放为 0。报告分子/分母，少量样本不声称统计充分；固定小课目标而非固定数量。

性能改进目标：相同输入/模型/ASR/硬件下语义阶段中位耗时较冻结基线下降 ≥30%，无效输出比例较基线至少减半，且上述质量不退化。这是待实测目标，不是已实现承诺；未达到须记录差距，不能事后改口径宣布提速。

SD-0 保存基线代码/契约与输入身份；实际对照在 SD-6 同宿主进行。每个 Profile 独立报告至少 3 次运行，固定并发、reasoning、缓存开关及计时起止；无效比例为 invalid 响应数/实际模型响应数，本地启动失败另计。列出失败和超时，不剔除后只展示成功中位数。基线无法完成时报告“无可比降幅”及完成率/绝对耗时预算，不用历史 V2 的 93 分 40 秒作为 mini 分母；此时不能宣称已达相对提速目标。基线为零 invalid 时目标为保持零。

首次真实批次先估算调用、成本与预计时长并记录限额；未知费用授权不能自动扩大。凭据缺失、主机不支持或限额不足均标明 `BLOCKED_REAL_MODEL_ACCEPTANCE`，完成其他不受阻工作。

### SD-7：收口、发布与恢复文档

按版本化契约/传输/执行/校验小步拆分超大模块，不与修 bug 同时全库重写。未证明无用的历史路径不删除。

更新 README、Solution/ADR、运维恢复、能力/版本矩阵、CHANGELOG（如采用）、本计划和 STATUS。软件版本依据实际发布范围另作决定；不能用“v2 目录”替代版本号。

交付可重建代码检查点、锁依赖安装证据、工程 gate、真实验收报告、成品路径与明确已知限制。不得自动 push、部署或批量迁移用户案例。发布前仍存在本计划 P1 时不能宣称稳定版完成。

## 8. 文件所有权与调度纪律

| 文件面 | 唯一责任方 | 并行限制 |
| --- | --- | --- |
| ADR/Solution/ExecPlan/STATUS、共享 Schema/DTO/迁移/锁 | 主编排/其唯一集成 Coder | 不分发并行写权限 |
| semantic_profiles/semantic_global/semantic_cache/新 transport | 当前语义工作包 Coder | 同期其他 Agent 只读 |
| stage_handlers/bootstrap/application pipeline | 主编排集成 | SD-1/2/3/4 串行改动 |
| 新 completion service/repository 与专项测试 | 当前后端 Coder | Schema/迁移先冻结 |
| cli/app.py 与 CLI 测试 | 当前 CLI Coder | auto/resume/preset/TUI 合并排序，不交叉写 |
| Web 组件与组件测试 | 当前 Web Coder | DTO 冻结；不私改 types/API 契约 |
| qa/pipeline.jsonl、qa/test-report.md、正式执行日志 | 可信 Runner/主编排证据服务 | Agent 不回写、修订或伪造旧记录 |

所有权是任务租约，不是多人永久拥有同一文件。每个候选结束释放；新任务重新确认清单。当前 M0 不支持多个需求并发，禁止两个 loop-run 指向同一交付分支。

共享文件的必要接入必须在最终 assurance 快照冻结之前完成。主编排不能在单次 Loop 运行期间另改主交付树；候选接受后若追加集成修改，形成新候选并重跑独立审阅和全部相关正式 gate，不沿用前一快照的 PASS。

## 9. QA、命令与证据

采用 qa-test-pipeline 的逐命令 request/result ID 关联和 append-only 规则；仓库更严格的 deny-default Runner、冻结快照和命令 allowlist 优先。每次先记录请求，再执行，再追加 PASS/FAIL/ERROR；纠正命令用新 ID，不改历史条目。

现有正式命令：`lint → [make, lint]`、`test → [make, test]` 必须通过，`doctor → [make, doctor]` 是可选环境检查。Tester 建议不能绕过 required_for_final。未来 `unit/local-integration/browser` 目标需先由主编排加入 Make 和 allowlist 并独立审查，未实现前不提供虚假命令。

开发者可重现的定向检查（已存在；不是当前 Loop 新增 command ID）：

```bash
# 此 cd 仅用于当前问题重现。
# 实施后在 SD-0 记录的新基线/当前候选根执行，不能在旧树跑测试证明新候选。
cd /Users/junhuaxu/Workspace/AGI/liveclip-ai-v2
.venv/bin/pytest -q tests/unit/test_semantic_profiles.py tests/unit/test_semantic_global_context_budget.py tests/unit/test_structured_repair_preflight.py
.venv/bin/pytest -q tests/unit/test_cli_retry.py tests/unit/test_selection.py tests/integration/test_cli_pipeline.py
make lint
make test
```

第一组检查语义/预算/修复；第二组检查已有 CLI/恢复/选择。新 completion、取消/并发测试随任务添加，不把旧测试通过当成新能力通过。全量 make test 包含本地 Mock AI 浏览器流程；真实 Provider gate 另列。

正式 gate 必须绑定同一 HEAD、工作树、Prompt/Schema/contract、锁依赖/toolchain 与日志 hash。任何影响结果的改动使相关审查/测试证据失效。日常用定向测试提速，任务候选仍满足现有 Loop 全量门，不降低门禁来省时间。

证据层级：

| Gate | 能证明什么 | 不能冒充什么 |
| --- | --- | --- |
| G0 静态/单元/契约 | 不变量、版本、边界、类型 | 真模型质量 |
| G1 本地集成/浏览器 | SQLite/CLI/API/Web/FFmpeg 协作 | 真实 ASR/LLM |
| G2 工程候选审查/Runner/Gateway | 此快照可以集成 | 产品真实验收完成 |
| G3 真实模型/恢复 | 模型回执、来源、完整产品链 | 仅凭调用成功认定内容好 |
| G4 成品/性能 | 实际视频、人工质量、时间成本 | 用历史旧版本替代新版本 |

## 10. Idempotency、恢复、取消与回滚

- Selection 使用稳定幂等键，记录一次性 checkpoint；重试重放原动作，不能依据变化后的列表重选覆盖人工决定。
- Delivery enqueue 复用既有事务幂等，意图绑定唯一 delivery_id；发布前后崩溃不能多分配版本或接受 stale master。
- 并发 resume 使用既有 lease/CAS/事务协调；权限在真实动作提交时重验，不以创建 intent 时权限永久授权。
- resume 调用者必须有当前项目所需操作权限；后台使用明确记录的执行主体重验，不能让低权限调用者借原 requester 权限推进任务。归档、成员移除、降权同样阻止后续动作；本轮不新增隐式接管权限。
- 已验证缓存保证不重付同一成功单元；远端已执行但本地回执尚未保存的模糊窗口不能宣称跨 Provider exactly-once，必须记录“不确定是否已执行”并使用受限恢复策略。
- watch 退出不取消；执行取消使用现有取消/租约协议。失去租约的工作者不能发布晚到结果。
- 迁移先备份、在副本上验证 upgrade/兼容恢复，不自动回滚真实库；代码回滚保留新版本数据可读，无法安全 downgrade 时用备份和受控恢复流程。
- 开发 Loop 崩溃与产品恢复不同：M0 中途会 blocked，检查证据后新建 Run；不能编辑 state.json、使用 --last 或假装断点续跑支持所有阶段。
- Loop 发布是逐文件原子替换，不是全仓事务；发布中断须核对源/目标清单及指纹，不能对已变动用户工作树盲目重放。

## 11. Definition of Done

- [ ] 所有本计划 P1 有失败回归、修复与独立复审证据。
- [ ] 新合同与缓存身份明确，旧配置/交付未被原地改写。
- [ ] auto 及恢复覆盖默认选择到真实 ZIP；手工选择、零结果、并发及中断正确。
- [ ] CLI/API/Web 推荐 preset 一致，完整 TUI 可见且 watch 无副作用。
- [ ] 所有正式工程门通过，P0/P1 未解决数为 0，没有陈旧/无关 PASS。
- [ ] 两个待发布 Profile 均有真实语义、媒体与恢复验收；未通过的 Profile 明确留在实验范围，不能默认为已验收。
- [ ] 质量与性能测量口径冻结，结果/差距/费用明确；2h/4h 未验收不得隐藏。
- [ ] 文档、精确命令、版本、成品和报告路径完整；产品不依赖开发会话。

只有 G0–G4 和上述事项完成才能称为稳定交付里程碑完成。若只有工程 gate，通过状态必须写“工程实现验证通过；真实验收阻塞”，不能使用无条件 completed。


## 12. Surprises、Decision Log 与风险

2026-09-12 PDT：SD-1A完成正式工程验收并精确集成。接受源码eb507a42，formal195929，
Q01–Q10、完整错误/唯一修复、任务归属审计、旧合同缓存兼容通过。实际Runner1212Python、
58Web、两类浏览器通过；当前120秒小课及字幕/质量报告/清单已检查。详见
[接受记录](../verification/stable-delivery-sd1a-accepted-2026-09-12.md)。

七次早期formal保持BLOCKED。每次仅在具体缺陷被验证修正后建立新有界run；ADR031–040
记录工具宿主、密封依赖、目录search、离线资产/受限浏览器IPC、嵌套快照、完整修复审计、
任务诊断路由、响应状态、多部件错误和小课产物留存。没有重置状态/预算或降低证据要求。

最后一轮曾因主机闲置/维护休眠有长墙钟间隔，活动计时与墙钟不同；实际pmset和QA记录保留。
仅使用随Loop进程结束释放的临时断言和一次30秒唤醒请求，不修改全局电源配置。
原树setup默认同步移除了可选local-asr依赖，随后按原锁恢复；模型权重和数据不变。

风险仍包括来源闭合、超长上下文、恢复成本放大、入口状态不一致、真实标签不足和硬件/权限
差异；分别由SD-1B至SD-6解决。不能把SD-1A工程门等同整个稳定交付或真实小课内容验收。
此前完整决策和逐轮失败历史存于[原ExecPlan快照](../verification/history/sd1a-exec-plan-before-acceptance-2026-09-12.md)。

## 13. Recovery Notes / 下一条任务

当前下一任务是[SD-4持久完成目标](liveclip-sd4-durable-completion.md)，从已集成的SD-3源码和当前文档建立独立候选。详见[SD-3接受记录](../verification/stable-delivery-sd3-accepted-2026-09-13.md)。

以下为SD-2历史交接：当时下一任务是[SD-2请求预算与无损传输](liveclip-sd2-semantic-transport.md)。从SD-1B接受源码
39405cbd及当前主编排文档建立独立候选，核对33文件发布回执6e23和集成后cc19验证。
ADR043冻结新V10/V11传输身份；完整初次/唯一修复请求在实际Provider边界计量，保留所有
来源、候选、风险和索引错误。旧配置、缓存与六份V5Schema保持兼容，不发布空配置开关。
仍不从HEAD-only clone或含用户data的原树直接运行Loop。详见
[SD-1B接受记录](../verification/stable-delivery-sd1b-accepted-2026-09-13.md)和SD-2至SD-5的独立ExecPlan。

继续遵守原有5角色、2plan/3code和allowlist Runner。只用记录的精确Coder session续接，
不使用--last；DONE/BLOCKED不重启。测试工件必须来自本轮执行根，旧PASS不能替代。
原树不直接loop-run；setup保留既有可选extra，不运行模型下载脚本替代依赖恢复。

## 14. Outcomes and Retrospective

SD-0至SD-4已完成工程验收，SD-5至SD-7仍待完成。质量门和单修复审计的多轮实际反例说明仅看
测试数不足以验收；完整同源证据、真实Task/SQLite失败状态和当前媒体工件均必要。
已将重复旧交接归档，保留字节和哈希，使当前STATUS/ExecPlan只指向真实的下一任务。
用户连续开发授权持续有效；未来真实批次仍需明确输入、成本/时长边界与实际内容评审。

2026-09-13 SD-1B收口：当前来源账本/风险/重载/缓存与保留工件已验收；
[记录](../verification/stable-delivery-sd1b-accepted-2026-09-13.md)保留精确身份、所有失败和真实验收限制。

2026-09-14 SD-4收口：持久化 Completion API、无客户端 Worker、人工选择与一个
Delivery ZIP 已完成正式合成工程验收和原树精确 CAS 发布；
[记录](../verification/stable-delivery-sd4-accepted-2026-09-14.md)列出正式 Runner、
独立产物审计、失败历史和真实模型/内容验收边界。下一步 SD-5。
