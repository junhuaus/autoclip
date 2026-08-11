# ADR-009：OpenRouter Whisper Large V3 作为默认真实 ASR

- 状态：Accepted
- 日期：2026-08-05

## 2026-08-11 修订

原决策第 3 项的 300 秒默认分块已被 90 秒取代；5 秒重叠和 24 MB 应用上限保持不变。原因是 OpenRouter JSON `input_audio` 还会产生 base64 开销，较短分块可稳定控制请求大小、单次失败代价和恢复粒度。`.env.example`、Settings、Solution、研究记录和真实运行证据统一采用 90 秒。该修订保留下面的历史决策文字，避免静默改写原 ADR。

## 背景

本机 Codex CLI 能分析候选转写，但不能从视频音轨产生可靠的带时间戳中文转写。用户明确指定使用 OpenRouter Key 访问 `openai/whisper-large-v3`。源视频约数十分钟到数小时，必须流式预处理、分块、可恢复并保留供应商调用证据。

## 决策

新增 `openrouter-codex` 组合模式，并将其设为真实运行默认值：

1. OpenRouter ASR Adapter 使用固定官方 Base URL、精确模型白名单、中文提示、`verbose_json`、词级与句段级时间戳。
2. Adapter 通过 OpenAI Python SDK 向 OpenRouter JSON `input_audio` 接口发送一个有界 M4A/AAC 分块；JSON 路径允许使用文档化的 `provider.options.groq.prompt`，避免 multipart 顶层 `prompt` 被静默忽略。SDK retry 关闭，由 LiveClip 统一重试。
3. 默认分块 300 秒、重叠 5 秒、大小上限 24 MB；每块按输入指纹缓存并可恢复。
4. 成功必须保存精确的 `X-Generation-Id`；普通 `x-request-id` 不能替代。保存请求/重试次数、延迟、音频秒数和经过有限非负校验的供应商 usage/cost；不硬编码价格。
5. ASR 输出映射到统一 `ASRChunkResult`，畸形响应确定性失败，绝不暗中切换 Mock。
6. Codex CLI 继续只做编辑，使用独立 ChatGPT 登录；OpenRouter Key 不传给 Codex 子进程。
7. `OPENROUTER_BASE_URL` 固定为 `https://openrouter.ai/api/v1`，避免配置型 SSRF 或凭据外送。

## 数据边界

上传的是本机预处理后的音频块，不是视频画面。音频离开本机后经过 OpenRouter 和它选择的上游模型供应商。候选转写随后单独发送给 Codex 云端推理。网页和 API 不返回 Key。

## 后果

- 优点：获得真实中文内容与词/句段时间戳；ASR 与编辑职责清晰；兼容现有长视频恢复机制。
- 代价：音频会上传到两个数据边界中的第一个边界；用户需管理 OpenRouter 额度与新 Key。
- 风险：OpenRouter 的具体上游、能力或超时会变化，因此模型、generation ID 和 usage 都进入持久证据，官方文档按日期核对。
- 验证限制：曾暴露的旧 Key 不得使用；只有本机配置重新生成的 Key 后，`make smoke-openrouter` 才能完成真实云端验收。
